"""
FastAPI 主应用入口
提供REST API和WebSocket接口
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time

from .config import CORS_ORIGINS, SCREEN_INTERVAL
from .models import ScreenFilter, CryptoScreenResult, RealtimeQuote
from .exchange import get_fetcher
from .screener import ScreeningEngine
from .websocket_manager import manager, poll_prices_fallback, broadcast_screen_results, binance_price_stream
from .indicators import compute_all_indicators, generate_buy_sell_signal
from .backtest import predict_gain, backtest_strategy
from .twitter import (
    get_twitter_sentiment,
    batch_get_twitter_sentiment,
    get_raw_tweets,
    get_cache_stats,
    KNOWN_ACCOUNTS,
)
from .contracts import get_contract_addresses, batch_get_contracts

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# 全局筛选引擎
_engine: Optional[ScreeningEngine] = None
_bg_tasks = []


def get_engine() -> ScreeningEngine:
    global _engine
    if _engine is None:
        _engine = ScreeningEngine(get_fetcher())
    return _engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("🚀 虚拟币筛选工具启动中...")

    # 启动后台筛选任务
    task1 = asyncio.create_task(background_screening_loop())
    _bg_tasks.append(task1)

    # 启动实时价格轮询任务（初始用 REST 轮询，之后可切换为 WS）
    task2 = asyncio.create_task(background_price_loop())
    _bg_tasks.append(task2)

    yield

    # 关闭时清理
    for t in _bg_tasks:
        t.cancel()
    await get_fetcher().close()
    logger.info("应用已关闭")


async def background_screening_loop():
    """后台定期筛选任务"""
    await asyncio.sleep(5)  # 等待应用完全启动
    while True:
        try:
            engine = get_engine()
            results = await engine.run_screening()
            if results:
                await broadcast_screen_results(results)
                logger.info(f"筛选完成，推送 {len(results)} 个结果")
        except Exception as e:
            logger.error(f"后台筛选任务出错: {e}")
        await asyncio.sleep(SCREEN_INTERVAL)


async def background_price_loop():
    """后台实时价格轮询（每5秒推送一次给前端）"""
    await asyncio.sleep(10)  # 等待筛选结果先出来
    while True:
        try:
            engine = get_engine()
            cached = engine.get_cached_results()
            if cached:
                # 只轮询已筛出的币种（降低API压力）
                symbols = list({r.symbol for r in cached[:50]})
                fetcher = get_fetcher()
                # 分别从币安和Gate拉
                binance_syms = [r.symbol for r in cached[:50] if r.exchange == "binance"][:30]
                gate_syms    = [r.symbol for r in cached[:50] if r.exchange == "gate"][:20]
                tasks = []
                if binance_syms:
                    tasks.append(fetcher.get_batch_quotes(binance_syms, "binance"))
                if gate_syms:
                    tasks.append(fetcher.get_batch_quotes(gate_syms, "gate"))
                if tasks:
                    all_quotes = {}
                    for res in await asyncio.gather(*tasks, return_exceptions=True):
                        if isinstance(res, dict):
                            all_quotes.update(res)
                    if all_quotes:
                        import time
                        await manager.broadcast({
                            "type": "price_update",
                            "data": {
                                s: {"price": q.price, "change_24h": q.change_24h, "volume_24h": q.volume_24h}
                                for s, q in all_quotes.items()
                            },
                            "timestamp": time.time()
                        })
        except Exception as e:
            logger.warning(f"实时价格推送出错: {e}")
        await asyncio.sleep(5)  # 每5秒推送一次


# ============= 创建FastAPI应用 =============
app = FastAPI(
    title="虚拟币智能筛选工具 API",
    description="实时筛选具有上涨潜力的低价虚拟币，提供技术指标、回测分析和买卖信号",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 开发环境全放开；生产环境替换为具体域名
    allow_credentials=False,   # allow_credentials=True 与 allow_origins=["*"] 不兼容
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============= REST API 接口 =============

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/api/screen", response_model=List[CryptoScreenResult])
async def get_screen_results(
    price_max: float = Query(1.0, description="最高价格（USDT）"),
    price_min: float = Query(0.0, description="最低价格（USDT）"),
    min_gain: float = Query(20.0, description="最低预测涨幅(%)"),
    max_risk: float = Query(0.5, description="最大风险系数(0-1)"),
    min_volume: float = Query(1_000_000, description="最低24h成交量(USDT)"),
    exchanges: str = Query("binance,gate", description="交易所（逗号分隔）"),
    active_twitter: bool = Query(False, description="只显示推特活跃的币"),
    refresh: bool = Query(False, description="强制重新筛选"),
):
    """获取筛选结果"""
    engine = get_engine()

    filter_cfg = ScreenFilter(
        price_max=price_max,
        price_min=price_min,
        min_predicted_gain=min_gain,
        max_risk_score=max_risk,
        min_volume=min_volume,
        exchanges=exchanges.split(","),
        require_active_twitter=active_twitter,
    )

    if refresh or not engine.get_cached_results():
        results = await engine.run_screening(filter_cfg)
    else:
        results = engine.get_cached_results()

    # ── 后端二次过滤：对缓存结果按前端传入的参数再筛一遍 ──
    if price_max > 0:
        results = [r for r in results if r.price <= price_max]
    if price_min > 0:
        results = [r for r in results if r.price >= price_min]
    if min_volume > 0:
        results = [r for r in results if r.volume_24h >= min_volume]
    if max_risk < 1.0:
        results = [r for r in results if r.risk is None or r.risk.risk_score <= max_risk]
    if exchanges and exchanges != "binance,gate":
        exc_list = [e.strip() for e in exchanges.split(",") if e.strip()]
        if exc_list:
            results = [r for r in results if r.exchange in exc_list]
    if active_twitter:
        from .models import TweetStatus
        results = [r for r in results if r.sentiment and r.sentiment.tweet_status == TweetStatus.ACTIVE]

    return results


@app.get("/api/screen/status")
async def get_screen_status():
    """获取筛选状态"""
    engine = get_engine()
    return {
        "last_screen_time": engine.get_last_screen_time(),
        "result_count": len(engine.get_cached_results()),
        "is_screening": engine._is_screening,
    }


@app.post("/api/screen/trigger")
async def trigger_screening(
    background_tasks: BackgroundTasks,
    filter_cfg: ScreenFilter = None
):
    """手动触发筛选"""
    if filter_cfg is None:
        filter_cfg = ScreenFilter()
    engine = get_engine()
    background_tasks.add_task(engine.run_screening, filter_cfg)
    return {"message": "筛选任务已启动", "timestamp": time.time()}


@app.get("/api/coin/{symbol}/analysis")
async def get_coin_analysis(symbol: str, exchange: str = "binance"):
    """获取单个币种的详细分析（仅支持 USDT 交易对）"""
    fetcher = get_fetcher()
    # 标准化并强制 USDT
    symbol = symbol.upper().replace("-", "/").replace("_USDT", "/USDT")
    if not symbol.endswith("/USDT"):
        symbol = symbol.split("/")[0] + "/USDT"
    if ":" in symbol:
        return JSONResponse(status_code=400, content={"error": "仅支持 USDT 现货交易对，不支持合约"})

    # 获取历史数据
    df = await fetcher.get_ohlcv(symbol, "1d", 365 * 3, exchange)
    if df is None or df.empty:
        return JSONResponse(status_code=404, content={"error": f"无法获取 {symbol} 的数据"})

    # 计算指标
    indicators = compute_all_indicators(df)

    # 获取实时价格
    quote = await fetcher.get_realtime_quote(symbol, exchange)
    price = quote.price if quote else float(df['close'].iloc[-1])

    # 生成信号
    signal = generate_buy_sell_signal(price, indicators, df)

    # 回测
    backtest = backtest_strategy(df)

    # 预测
    pred_5d = predict_gain(df, 5)
    pred_10d = predict_gain(df, 10)

    return {
        "symbol": symbol,
        "exchange": exchange,
        "price": price,
        "predicted_gain_5d": pred_5d,
        "predicted_gain_10d": pred_10d,
        "technicals": indicators.dict() if indicators else {},
        "signal": signal.dict(),
        "backtest": backtest.dict(),
    }


@app.get("/api/coin/{symbol}/klines")
async def get_klines(
    symbol: str,
    exchange: str = "binance",
    timeframe: str = "1d",
    limit: int = 90
):
    """获取K线数据（仅支持 USDT 交易对）"""
    fetcher = get_fetcher()
    symbol = symbol.upper().replace("-", "/").replace("_USDT", "/USDT")
    if not symbol.endswith("/USDT"):
        symbol = symbol.split("/")[0] + "/USDT"
    if ":" in symbol:
        return JSONResponse(status_code=400, content={"error": "仅支持 USDT 现货交易对"})
    df = await fetcher.get_ohlcv(symbol, timeframe, limit, exchange)

    if df is None or df.empty:
        return JSONResponse(status_code=404, content={"error": "数据获取失败"})

    records = []
    for idx, row in df.iterrows():
        records.append({
            "time": idx.isoformat(),
            "open": row['open'],
            "high": row['high'],
            "low": row['low'],
            "close": row['close'],
            "volume": row['volume'],
        })

    return {"symbol": symbol, "timeframe": timeframe, "data": records}


@app.get("/api/realtime/{symbol}")
async def get_realtime_price(symbol: str, exchange: str = "binance"):
    """获取实时价格（仅支持 USDT 交易对）"""
    symbol = symbol.upper().replace("-", "/").replace("_USDT", "/USDT")
    if not symbol.endswith("/USDT"):
        symbol = symbol.split("/")[0] + "/USDT"
    if ":" in symbol:
        return JSONResponse(status_code=400, content={"error": "仅支持 USDT 现货交易对"})
    cached = manager.get_latest_prices().get(symbol)
    if cached:
        return cached

    fetcher = get_fetcher()
    quote = await fetcher.get_realtime_quote(symbol, exchange)
    if quote:
        return quote.dict()
    return JSONResponse(status_code=404, content={"error": "无法获取实时价格"})


@app.get("/api/realtime/batch")
async def get_batch_realtime(
    symbols: str = Query(..., description="交易对列表，逗号分隔"),
    exchange: str = "binance"
):
    """批量获取实时价格（自动过滤非USDT交易对）"""
    raw_list = [s.strip().upper().replace("-", "/").replace("_USDT", "/USDT")
                for s in symbols.split(",")]
    # 只保留 USDT 现货
    symbol_list = [s if s.endswith("/USDT") else s.split("/")[0] + "/USDT"
                   for s in raw_list if ":" not in s]
    fetcher = get_fetcher()
    quotes = await fetcher.get_batch_quotes(symbol_list, exchange)
    return {s: q.dict() for s, q in quotes.items()}


# ============= WebSocket 接口 =============

@app.websocket("/ws/realtime")
async def websocket_realtime(websocket: WebSocket):
    """
    WebSocket实时价格推送
    客户端连接后自动接收价格更新
    """
    await manager.connect(websocket)
    try:
        # 启动轮询任务（如果还没有启动）
        while True:
            # 接收客户端消息（心跳 or 订阅指令）
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                try:
                    msg = json.loads(data) if data else {}
                except Exception:
                    msg = {}
                if msg.get("type") == "ping":
                    await websocket.send_text('{"type":"pong"}')
            except asyncio.TimeoutError:
                # 发送心跳
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket错误: {e}")
        manager.disconnect(websocket)


@app.websocket("/ws/screen")
async def websocket_screen(websocket: WebSocket):
    """
    WebSocket筛选结果推送
    """
    await manager.connect(websocket)
    try:
        # 立即推送当前缓存的筛选结果
        engine = get_engine()
        cached = engine.get_cached_results()
        if cached:
            import json
            await websocket.send_text(json.dumps({
                "type": "screen_results",
                "data": [r.dict() for r in cached[:50]],
                "count": len(cached),
                "timestamp": time.time()
            }, default=str))

        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=60)
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        manager.disconnect(websocket)


# ============= 合约地址 API =============

@app.get("/api/coin/{symbol}/contracts")
async def get_coin_contracts(symbol: str):
    """
    查询币种在各链上的合约地址（通过 CoinGecko）。
    symbol 传 BASE 即可，如 PEPE、BONK，也支持 PEPE/USDT 格式。
    """
    base = symbol.upper().replace("/USDT", "").replace("USDT", "").replace("-", "").strip()
    contracts = await get_contract_addresses(base)
    return {
        "coin": base,
        "contracts": contracts,  # { "ETH": "0x...", "BSC": "0x..." }
        "count": len(contracts),
    }


@app.post("/api/contracts/batch")
async def batch_coin_contracts(symbols: List[str]):
    """批量查询多个币种的合约地址"""
    bases = [s.upper().replace("/USDT", "").replace("USDT", "").strip() for s in symbols]
    results = await batch_get_contracts(bases, concurrency=3)
    return {"results": results, "count": len(results)}


# ============= 推特 API 接口 =============

@app.get("/api/twitter/{coin}/sentiment")
async def get_coin_twitter_sentiment(
    coin: str,
    force_refresh: bool = Query(False, description="是否强制刷新（忽略缓存）"),
):
    """
    获取单个币种的推特情绪分析结果。
    - 自动匹配已知官方账号，未知账号尝试搜索发现
    - 默认使用缓存（TTL 1小时），force_refresh=true 强制重爬
    """
    score = await get_twitter_sentiment(coin.upper(), force_refresh=force_refresh)
    return score.dict()


@app.get("/api/twitter/{coin}/tweets")
async def get_coin_tweets(coin: str):
    """
    返回币种最新原始推文列表（最多30条）。
    包含：推文文本、发布时间、点赞数、转推数、回复数、互动量。
    """
    tweets = await get_raw_tweets(coin.upper())
    return {
        "coin": coin.upper(),
        "count": len(tweets),
        "tweets": tweets,
        "timestamp": time.time(),
    }


@app.post("/api/twitter/batch")
async def batch_twitter_sentiment(
    coins: List[str],
    concurrency: int = Query(5, description="并发爬取数量上限"),
    force_refresh: bool = Query(False),
):
    """
    批量获取多个币种的推特情绪（并发执行）。
    请求体：["BTC", "ETH", "SOL", ...]
    """
    results = await batch_get_twitter_sentiment(
        coins, concurrency=concurrency, force_refresh=force_refresh
    )
    return {
        "results": {k: v.dict() for k, v in results.items()},
        "count": len(results),
        "timestamp": time.time(),
    }


@app.get("/api/twitter/accounts")
async def list_known_accounts():
    """返回已内置的推特账号映射表（coin → @username）"""
    return {
        "accounts": KNOWN_ACCOUNTS,
        "total": len(KNOWN_ACCOUNTS),
    }


@app.get("/api/twitter/cache/stats")
async def twitter_cache_stats():
    """返回推特缓存状态（调试 / 监控用）"""
    return get_cache_stats()
