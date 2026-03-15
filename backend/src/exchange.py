"""
交易所数据采集模块
支持币安(Binance) 和 Gate.io 的实时行情、K线、深度数据
"""
import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import httpx
import ccxt.async_support as ccxt

from .config import (
    BINANCE_API_KEY, BINANCE_SECRET_KEY,
    GATE_API_KEY, GATE_SECRET_KEY,
    BINANCE_REST_URL, GATE_REST_URL,
    VOLUME_MIN, PRICE_MAX, PRICE_MIN
)
from .models import CryptoBasic, RealtimeQuote

logger = logging.getLogger(__name__)


class ExchangeDataFetcher:
    """统一的交易所数据采集器"""

    def __init__(self):
        self.binance = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_SECRET_KEY,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        self.gate = ccxt.gateio({
            'apiKey': GATE_API_KEY,
            'secret': GATE_SECRET_KEY,
            'enableRateLimit': True,
        })
        self._cache: Dict[str, dict] = {}
        self._cache_time: Dict[str, float] = {}

    async def close(self):
        await self.binance.close()
        await self.gate.close()

    # ===========================
    # 获取市场列表（USDT交易对）
    # ===========================
    async def get_usdt_pairs(self, exchange: str = "binance") -> List[CryptoBasic]:
        """获取交易所所有USDT交易对的当前行情"""
        try:
            exc = self.binance if exchange == "binance" else self.gate
            tickers = await exc.fetch_tickers()

            results = []
            for symbol, ticker in tickers.items():
                # 统一格式：只保留 BASE/USDT 格式（过滤杠杆、永续合约等）
                if '/USDT' not in symbol:
                    continue
                # 过滤带 ':' 的永续合约（如 BTC/USDT:USDT）
                if ':' in symbol:
                    continue
                # 标准化 symbol：某些交易所用 BASE_USDT，统一转成 BASE/USDT
                norm_symbol = symbol.replace('_USDT', '/USDT').replace('-USDT', '/USDT')
                parts = norm_symbol.split('/')
                if len(parts) != 2 or parts[1] != 'USDT':
                    continue
                base = parts[0].strip()
                if not base:
                    continue

                price = ticker.get('last') or 0
                volume_24h = (ticker.get('quoteVolume') or 0)

                # 过滤条件
                if price <= 0 or price > PRICE_MAX or price < PRICE_MIN:
                    continue
                if volume_24h < VOLUME_MIN:
                    continue

                results.append(CryptoBasic(
                    symbol=norm_symbol,          # 统一存 BASE/USDT 格式
                    base=base,
                    exchange=exchange,
                    price=float(price),
                    price_change_24h=float(ticker.get('percentage') or 0),
                    volume_24h=float(volume_24h),
                    high_24h=float(ticker.get('high') or 0),
                    low_24h=float(ticker.get('low') or 0),
                ))

            logger.info(f"[{exchange}] 获取到 {len(results)} 个符合条件的USDT交易对")
            return results

        except Exception as e:
            logger.error(f"获取 {exchange} 市场列表失败: {e}")
            return []

    # ===========================
    # 获取K线历史数据（仅限 USDT 交易对）
    # ===========================
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 365 * 3,  # 默认3年
        exchange: str = "binance"
    ) -> pd.DataFrame:
        """获取K线数据，返回DataFrame（只处理 USDT 现货）"""
        # 统一格式 + 校验
        norm = symbol.replace('_USDT', '/USDT').replace('-USDT', '/USDT').upper()
        if not norm.endswith('/USDT') or ':' in norm:
            logger.warning(f"非USDT交易对，跳过K线请求: {symbol}")
            return pd.DataFrame()
        try:
            exc = self.binance if exchange == "binance" else self.gate
            ohlcv = await exc.fetch_ohlcv(norm, timeframe, limit=limit)

            if not ohlcv:
                return pd.DataFrame()

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df.astype(float)
            return df

        except Exception as e:
            logger.warning(f"获取K线失败 {norm} @ {exchange}: {e}")
            return pd.DataFrame()

    # ===========================
    # 获取多时框K线（1d + 4h + 1h）
    # ===========================
    async def get_multi_timeframe(
        self,
        symbol: str,
        exchange: str = "binance"
    ) -> Dict[str, pd.DataFrame]:
        """并发获取多个时间框架K线"""
        tasks = {
            "1d": self.get_ohlcv(symbol, "1d", 365, exchange),
            "4h": self.get_ohlcv(symbol, "4h", 720, exchange),
            "1h": self.get_ohlcv(symbol, "1h", 168, exchange),
        }
        results = {}
        for tf, coro in tasks.items():
            results[tf] = await coro
        return results

    # ===========================
    # 实时报价（单币，仅限 USDT 交易对）
    # ===========================
    async def get_realtime_quote(self, symbol: str, exchange: str = "binance") -> Optional[RealtimeQuote]:
        # 统一格式
        norm = symbol.replace('_USDT', '/USDT').replace('-USDT', '/USDT').upper()
        # 强制只处理 USDT 现货交易对
        if not norm.endswith('/USDT') or ':' in norm:
            logger.warning(f"非USDT交易对，跳过: {symbol}")
            return None
        try:
            exc = self.binance if exchange == "binance" else self.gate
            ticker = await exc.fetch_ticker(norm)
            return RealtimeQuote(
                symbol=norm,
                exchange=exchange,
                price=float(ticker.get('last') or 0),
                change_24h=float(ticker.get('percentage') or 0),
                volume_24h=float(ticker.get('quoteVolume') or 0),
                timestamp=float(ticker.get('timestamp') or 0) / 1000,
                bid=float(ticker.get('bid') or 0) if ticker.get('bid') else None,
                ask=float(ticker.get('ask') or 0) if ticker.get('ask') else None,
            )
        except Exception as e:
            logger.warning(f"获取实时报价失败 {norm}: {e}")
            return None

    # ===========================
    # 批量实时报价（多币种，仅限 USDT 交易对）
    # ===========================
    async def get_batch_quotes(
        self,
        symbols: List[str],
        exchange: str = "binance"
    ) -> Dict[str, RealtimeQuote]:
        """批量获取实时价格，只处理 USDT 现货交易对"""
        try:
            # 先过滤：只保留 USDT 现货，统一标准化格式
            usdt_symbols = []
            for s in symbols:
                norm = s.replace('_USDT', '/USDT').replace('-USDT', '/USDT').upper()
                if norm.endswith('/USDT') and ':' not in norm:
                    usdt_symbols.append(norm)

            if not usdt_symbols:
                return {}

            exc = self.binance if exchange == "binance" else self.gate
            tickers = await exc.fetch_tickers(usdt_symbols)
            result = {}
            for symbol, ticker in tickers.items():
                if not ticker.get('last'):
                    continue
                # 标准化 symbol key，与 CryptoBasic 保持一致
                norm_sym = symbol.replace('_USDT', '/USDT').replace('-USDT', '/USDT').upper()
                if not norm_sym.endswith('/USDT') or ':' in norm_sym:
                    continue
                result[norm_sym] = RealtimeQuote(
                    symbol=norm_sym,
                    exchange=exchange,
                    price=float(ticker['last']),
                    change_24h=float(ticker.get('percentage') or 0),
                    volume_24h=float(ticker.get('quoteVolume') or 0),
                    timestamp=datetime.now().timestamp(),
                )
            return result
        except Exception as e:
            logger.error(f"批量获取报价失败: {e}")
            return {}

    # ===========================
    # 获取合并后的双交易所数据
    # ===========================
    async def get_all_usdt_pairs(self) -> List[CryptoBasic]:
        """并发获取币安+Gate所有USDT交易对"""
        binance_task = self.get_usdt_pairs("binance")
        gate_task = self.get_usdt_pairs("gate")
        binance_coins, gate_coins = await asyncio.gather(binance_task, gate_task)

        # 合并，优先保留币安数据
        seen = set()
        merged = []
        for coin in binance_coins:
            if coin.base not in seen:
                seen.add(coin.base)
                merged.append(coin)

        # Gate.io 补充没有的币种
        for coin in gate_coins:
            if coin.base not in seen:
                seen.add(coin.base)
                merged.append(coin)

        logger.info(f"合并后共 {len(merged)} 个唯一币种")
        return merged


# 全局单例
_fetcher: Optional[ExchangeDataFetcher] = None


def get_fetcher() -> ExchangeDataFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = ExchangeDataFetcher()
    return _fetcher
