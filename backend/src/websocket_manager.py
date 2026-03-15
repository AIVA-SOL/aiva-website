"""
WebSocket 实时数据推送
连接币安和Gate.io的WebSocket流，实时推送价格到前端
"""
import asyncio
import json
import logging
import time
from typing import Set, Dict
import websockets
from fastapi import WebSocket
from .config import BINANCE_WS_URL, REALTIME_INTERVAL
from .models import RealtimeQuote
from .exchange import get_fetcher

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理器（管理所有前端客户端连接）"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._latest_prices: Dict[str, dict] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"新客户端连接，当前连接数: {len(self.active_connections)}")

        # 立即推送当前缓存的价格数据
        if self._latest_prices:
            try:
                await websocket.send_text(json.dumps({
                    "type": "price_snapshot",
                    "data": self._latest_prices,
                    "timestamp": time.time()
                }))
            except:
                pass

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"客户端断开，当前连接数: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """广播消息给所有连接的客户端"""
        if not self.active_connections:
            return
        text = json.dumps(message, ensure_ascii=False, default=str)
        dead_connections = set()
        for ws in self.active_connections.copy():
            try:
                await ws.send_text(text)
            except Exception as e:
                dead_connections.add(ws)
        for ws in dead_connections:
            self.active_connections.discard(ws)

    def update_price(self, symbol: str, data: dict):
        self._latest_prices[symbol] = data

    def get_latest_prices(self) -> Dict[str, dict]:
        return self._latest_prices


# 全局连接管理器
manager = ConnectionManager()


async def binance_price_stream(symbols: list):
    """
    连接币安WebSocket，订阅多个交易对的实时ticker
    """
    if not symbols:
        return

    # 构建Stream名称（小写）
    streams = "/".join([f"{s.lower().replace('/', '')}@miniTicker" for s in symbols[:50]])
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                logger.info(f"币安WebSocket已连接，订阅 {len(symbols)} 个交易对")
                async for message in ws:
                    try:
                        data = json.loads(message)
                        stream_data = data.get('data', {})
                        if stream_data.get('e') == '24hrMiniTicker':
                            symbol = stream_data['s']
                            # 将 BTCUSDT 转为 BTC/USDT
                            formatted = symbol[:-4] + '/USDT' if symbol.endswith('USDT') else symbol
                            price_data = {
                                "symbol": formatted,
                                "exchange": "binance",
                                "price": float(stream_data.get('c', 0)),
                                "change_24h": 0,
                                "volume_24h": float(stream_data.get('q', 0)),
                                "high_24h": float(stream_data.get('h', 0)),
                                "low_24h": float(stream_data.get('l', 0)),
                                "timestamp": time.time(),
                            }
                            manager.update_price(formatted, price_data)
                    except Exception as e:
                        logger.debug(f"解析WebSocket消息失败: {e}")

        except Exception as e:
            logger.warning(f"币安WebSocket断开，5秒后重连: {e}")
            await asyncio.sleep(5)


async def poll_prices_fallback(symbols: list, exchange: str = "binance"):
    """
    降级方案：轮询REST API获取实时价格（当WebSocket不可用时）
    """
    fetcher = get_fetcher()
    while True:
        try:
            quotes = await fetcher.get_batch_quotes(symbols[:100], exchange)
            for symbol, quote in quotes.items():
                price_data = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "price": quote.price,
                    "change_24h": quote.change_24h,
                    "volume_24h": quote.volume_24h,
                    "timestamp": quote.timestamp,
                }
                manager.update_price(symbol, price_data)

            # 广播给所有前端
            if quotes:
                await manager.broadcast({
                    "type": "price_update",
                    "data": {s: {
                        "price": q.price,
                        "change_24h": q.change_24h,
                        "volume_24h": q.volume_24h,
                    } for s, q in quotes.items()},
                    "timestamp": time.time()
                })

        except Exception as e:
            logger.warning(f"轮询价格失败: {e}")

        await asyncio.sleep(REALTIME_INTERVAL)


async def broadcast_screen_results(results: list):
    """推送筛选结果到所有客户端"""
    if results:
        await manager.broadcast({
            "type": "screen_results",
            "data": [r.dict() for r in results],
            "count": len(results),
            "timestamp": time.time()
        })
