"""
核心筛选引擎
整合技术指标、回测、风险、情绪数据，输出综合评分和筛选结果
"""
import asyncio
import logging
from typing import List, Dict, Optional
from datetime import datetime
import pandas as pd

from .config import (
    TARGET_GAIN_MIN, RISK_SCORE_MAX, PRICE_MAX, PRICE_MIN,
    VOLUME_MIN, SCREEN_INTERVAL
)
from .models import (
    CryptoBasic, CryptoScreenResult, ScreenFilter,
    TechnicalIndicators, RiskLevel
)
from .exchange import ExchangeDataFetcher
from .indicators import compute_all_indicators, generate_buy_sell_signal
from .backtest import backtest_strategy, predict_gain
from .risk import compute_risk_metrics
from .twitter import get_twitter_sentiment

logger = logging.getLogger(__name__)


class ScreeningEngine:
    """虚拟币智能筛选引擎"""

    def __init__(self, fetcher: ExchangeDataFetcher):
        self.fetcher = fetcher
        self._results: List[CryptoScreenResult] = []
        self._last_screen_time: Optional[datetime] = None
        self._btc_df: Optional[pd.DataFrame] = None
        self._is_screening = False

    async def _load_btc_reference(self):
        """加载BTC参考数据用于相关性计算"""
        try:
            df = await self.fetcher.get_ohlcv("BTC/USDT", "1d", 90, "binance")
            self._btc_df = df
        except:
            pass

    async def _analyze_single(
        self,
        coin: CryptoBasic,
        filter_cfg: ScreenFilter
    ) -> Optional[CryptoScreenResult]:
        """
        对单个币种进行完整分析
        """
        try:
            # 1. 获取历史K线（3年日线）
            df = await self.fetcher.get_ohlcv(
                coin.symbol, "1d", 365 * 3, coin.exchange
            )
            if df is None or len(df) < 60:
                return None

            # 2. 计算技术指标
            indicators = compute_all_indicators(df)
            if not indicators:
                return None

            # 3. 预测未来涨幅
            pred_5d = predict_gain(df, days=5)
            pred_10d = predict_gain(df, days=10)

            # 4. 快速预过滤：预测涨幅不够就跳过
            if max(pred_5d, pred_10d) < filter_cfg.min_predicted_gain:
                return None

            # 5. 回测（3年）
            backtest = backtest_strategy(df)

            # 6. 风险评估
            risk = compute_risk_metrics(
                df,
                volume_24h=coin.volume_24h,
                market_cap=coin.market_cap,
                btc_df=self._btc_df
            )

            # 风险过滤
            if risk.risk_score > filter_cfg.max_risk_score:
                return None

            # 7. 推特情绪（加超时保护，避免爬取卡死导致筛选挂起）
            try:
                sentiment = await asyncio.wait_for(
                    get_twitter_sentiment(coin.base), timeout=15.0
                )
            except asyncio.TimeoutError:
                from .models import SentimentScore, TweetStatus
                sentiment = SentimentScore(tweet_status=TweetStatus.NO_ACCOUNT, tweet_score=50.0)
            except Exception:
                from .models import SentimentScore, TweetStatus
                sentiment = SentimentScore(tweet_status=TweetStatus.NO_ACCOUNT, tweet_score=50.0)

            # 8. 生成买卖信号
            signal = generate_buy_sell_signal(coin.price, indicators, df)

            # 9. 综合评分（0-100）
            score = _compute_composite_score(
                pred_5d, pred_10d,
                indicators, backtest, risk, sentiment
            )

            # 最低分过滤
            if score < filter_cfg.min_score:
                return None

            # 10. 生成标签
            tags = _generate_tags(indicators, risk, sentiment, signal, pred_5d)

            return CryptoScreenResult(
                symbol=coin.symbol,
                base=coin.base,
                exchange=coin.exchange,
                price=coin.price,
                price_change_24h=coin.price_change_24h,
                volume_24h=coin.volume_24h,
                market_cap=coin.market_cap,
                predicted_gain_5d=pred_5d,
                predicted_gain_10d=pred_10d,
                score=round(score, 1),
                technicals=indicators,
                sentiment=sentiment,
                backtest=backtest,
                risk=risk,
                signal=signal,
                tags=tags,
            )

        except Exception as e:
            logger.debug(f"分析 {coin.symbol} 失败: {e}")
            return None

    async def run_screening(
        self,
        filter_cfg: ScreenFilter = None,
        max_coins: int = 200
    ) -> List[CryptoScreenResult]:
        """
        执行完整筛选流程
        """
        if self._is_screening:
            logger.info("筛选正在进行中，返回上次结果")
            return self._results

        self._is_screening = True
        if filter_cfg is None:
            filter_cfg = ScreenFilter()

        logger.info("开始执行虚拟币筛选...")

        try:
            # 加载BTC参考数据
            await self._load_btc_reference()

            # 获取所有候选币种
            all_coins = await self.fetcher.get_all_usdt_pairs()
            logger.info(f"候选币种总数: {len(all_coins)}")

            # 按交易所过滤
            if filter_cfg.exchanges:
                all_coins = [c for c in all_coins if c.exchange in filter_cfg.exchanges]

            # 按成交量排序，优先分析高流动性币种
            all_coins.sort(key=lambda x: x.volume_24h, reverse=True)
            all_coins = all_coins[:max_coins]

            # 并发分析（限制并发数避免被限速）
            results = []
            batch_size = 10
            for i in range(0, len(all_coins), batch_size):
                batch = all_coins[i:i + batch_size]
                tasks = [self._analyze_single(coin, filter_cfg) for coin in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in batch_results:
                    if isinstance(r, CryptoScreenResult):
                        results.append(r)
                await asyncio.sleep(0.5)  # 限速

            # 按综合评分排序
            results.sort(key=lambda x: x.score, reverse=True)
            self._results = results
            self._last_screen_time = datetime.now()

            logger.info(f"筛选完成，符合条件的币种: {len(results)} 个")
            return results

        finally:
            self._is_screening = False

    def get_cached_results(self) -> List[CryptoScreenResult]:
        return self._results

    def get_last_screen_time(self) -> Optional[str]:
        if self._last_screen_time:
            return self._last_screen_time.isoformat()
        return None


def _compute_composite_score(
    pred_5d: float,
    pred_10d: float,
    indicators: TechnicalIndicators,
    backtest,
    risk,
    sentiment
) -> float:
    """
    综合评分算法（0-100）
    权重：预测涨幅30%，技术指标25%，回测胜率20%，风险15%，情绪10%
    """
    score = 0.0

    # --- 预测涨幅（30%）---
    max_pred = max(pred_5d, pred_10d)
    pred_score = min(100, max(0, (max_pred - 10) / 40 * 100))
    score += pred_score * 0.30

    # --- 技术指标（25%）---
    tech_score = 50.0
    if indicators:
        rsi = indicators.rsi_14 or 50
        if rsi < 35:
            tech_score += 25
        elif rsi < 45:
            tech_score += 15
        elif rsi > 70:
            tech_score -= 20

        if indicators.macd_hist and indicators.macd_hist > 0:
            tech_score += 10
        if indicators.bb_lower and indicators.bb_lower > 0:
            pass  # 已在RSI中体现

        tech_score = max(0, min(100, tech_score))
    score += tech_score * 0.25

    # --- 回测胜率（20%）---
    bt_score = 0.0
    if backtest and backtest.signal_count > 0:
        bt_score = min(100, backtest.win_rate * 1.2)
    score += bt_score * 0.20

    # --- 风险（15%，风险越低分越高）---
    risk_score_val = (1.0 - (risk.risk_score if risk else 0.5)) * 100
    score += risk_score_val * 0.15

    # --- 情绪（10%）---
    sent_score = sentiment.tweet_score if sentiment else 50.0
    score += sent_score * 0.10

    return round(min(100, max(0, score)), 2)


def _generate_tags(indicators, risk, sentiment, signal, pred_5d: float) -> List[str]:
    """根据分析结果生成可读标签"""
    tags = []

    if indicators:
        if indicators.rsi_14 and indicators.rsi_14 < 35:
            tags.append("RSI超卖")
        if indicators.macd_hist and indicators.macd_hist > 0 and indicators.macd and indicators.macd < 0:
            tags.append("MACD底部金叉")
        elif indicators.macd_hist and indicators.macd_hist > 0:
            tags.append("MACD金叉")
        if indicators.bb_width and indicators.bb_width < 0.03:
            tags.append("布林收缩")

    if risk:
        if risk.risk_level == RiskLevel.LOW:
            tags.append("低风险")
        if risk.pump_dump_risk < 0.2:
            tags.append("价格稳健")

    if sentiment:
        from .models import TweetStatus
        if sentiment.tweet_status == TweetStatus.ACTIVE:
            tags.append("推特活跃")
        if sentiment.tweet_score > 65:
            tags.append("情绪正向")

    if pred_5d >= 20:
        tags.append(f"预期+{pred_5d:.0f}%")

    if signal and signal.signal.value in ["BUY", "STRONG_BUY"]:
        tags.append("买入信号")

    return tags
