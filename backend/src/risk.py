"""
风险评估模块
计算综合风险系数：波动率、流动性、与BTC相关性、拉盘风险等
"""
import numpy as np
import pandas as pd
from .models import RiskMetrics, RiskLevel
import logging

logger = logging.getLogger(__name__)


def calculate_volatility(df: pd.DataFrame, period: int = 30) -> float:
    """计算30日年化波动率"""
    if df is None or len(df) < period:
        return 1.0
    returns = df['close'].pct_change().dropna().tail(period)
    vol = returns.std() * np.sqrt(365) * 100
    return round(float(vol), 2)


def calculate_liquidity_score(volume_24h: float, market_cap: float) -> float:
    """
    流动性评分（0-1，越高越好）
    基于成交量/市值比
    """
    if market_cap is None or market_cap <= 0:
        return 0.3  # 无市值数据，保守估计
    ratio = volume_24h / market_cap
    # ratio越高，流动性越好
    score = min(1.0, ratio * 10)
    return round(float(score), 3)


def detect_pump_dump_risk(df: pd.DataFrame) -> float:
    """
    检测拉盘砸盘风险（0-1，越高风险越大）
    特征：短时间内巨幅涨跌、成交量异常
    """
    if df is None or len(df) < 14:
        return 0.5

    try:
        close = df['close']
        volume = df['volume']

        # 计算7日内最大单日涨幅
        max_1d_gain = close.pct_change().tail(7).max() * 100
        # 计算成交量标准差
        vol_std = volume.tail(30).std() / (volume.tail(30).mean() + 1e-6)

        risk = 0.0
        if max_1d_gain > 30:
            risk += 0.3
        elif max_1d_gain > 20:
            risk += 0.2
        if vol_std > 3:
            risk += 0.2
        elif vol_std > 2:
            risk += 0.1

        # 检查是否有价格哑铃形（快涨快跌）
        tail = close.tail(14)
        high_point = tail.max()
        current = tail.iloc[-1]
        if high_point > 0 and current < high_point * 0.7:
            risk += 0.2

        return round(min(1.0, risk), 3)
    except:
        return 0.5


def calculate_btc_correlation(coin_df: pd.DataFrame, btc_df: pd.DataFrame) -> float:
    """计算与BTC的30日价格相关性"""
    if coin_df is None or btc_df is None or len(coin_df) < 14 or len(btc_df) < 14:
        return 0.7  # 默认高相关

    try:
        coin_ret = coin_df['close'].pct_change().dropna().tail(30)
        btc_ret = btc_df['close'].pct_change().dropna().tail(30)

        min_len = min(len(coin_ret), len(btc_ret))
        if min_len < 10:
            return 0.7

        corr = float(coin_ret.tail(min_len).corr(btc_ret.tail(min_len)))
        return round(corr, 3)
    except:
        return 0.7


def compute_risk_metrics(
    df: pd.DataFrame,
    volume_24h: float,
    market_cap: float = None,
    btc_df: pd.DataFrame = None
) -> RiskMetrics:
    """计算综合风险指标"""
    volatility = calculate_volatility(df)
    liquidity = calculate_liquidity_score(volume_24h, market_cap or volume_24h * 10)
    pump_risk = detect_pump_dump_risk(df)
    btc_corr = calculate_btc_correlation(df, btc_df)

    # 综合风险评分（0-1，越小越安全）
    # 波动率高 → 风险高；流动性低 → 风险高；拉盘风险高 → 风险高
    vol_score = min(1.0, volatility / 200)  # 200%以上年化波动率=最高风险
    liquidity_risk = 1.0 - liquidity
    risk_score = (
        vol_score * 0.35 +
        liquidity_risk * 0.25 +
        pump_risk * 0.30 +
        max(0, (1 - btc_corr)) * 0.10  # 相关性低的小币风险略高
    )
    risk_score = round(min(1.0, risk_score), 3)

    if risk_score < 0.3:
        risk_level = RiskLevel.LOW
    elif risk_score < 0.6:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.HIGH

    return RiskMetrics(
        risk_score=risk_score,
        risk_level=risk_level,
        volatility_30d=volatility,
        liquidity_score=liquidity,
        correlation_btc=btc_corr,
        pump_dump_risk=pump_risk,
    )
