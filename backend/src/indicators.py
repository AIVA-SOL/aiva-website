"""
技术指标计算模块
包含：RSI, MACD, 布林带, EMA, KDJ, ATR, 量能分析等
"""
import numpy as np
import pandas as pd
from typing import Optional, Dict, Tuple
from .models import TechnicalIndicators, BuySellSignal, SignalType
import logging

logger = logging.getLogger(__name__)


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """计算RSI相对强弱指标"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def calculate_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """计算MACD指标，返回(macd, signal, histogram)"""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist


def calculate_bollinger(
    series: pd.Series,
    period: int = 20,
    std_factor: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """计算布林带，返回(upper, middle, lower)"""
    middle = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = middle + std_factor * std
    lower = middle - std_factor * std
    return upper, middle, lower


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算ATR真实波幅"""
    high = df['high']
    low = df['low']
    close = df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def calculate_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3
) -> Tuple[pd.Series, pd.Series]:
    """计算KDJ随机指标"""
    lowest_low = df['low'].rolling(k_period).min()
    highest_high = df['high'].rolling(k_period).max()
    k = 100 * (df['close'] - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k.fillna(50), d.fillna(50)


def calculate_volume_trend(df: pd.DataFrame, period: int = 20) -> Dict:
    """成交量趋势分析"""
    vol_ma = df['volume'].rolling(period).mean()
    latest_vol = df['volume'].iloc[-1]
    vol_ratio = latest_vol / vol_ma.iloc[-1] if vol_ma.iloc[-1] > 0 else 1.0

    # 量价关系
    price_up = df['close'].iloc[-1] > df['close'].iloc[-2]
    vol_up = latest_vol > vol_ma.iloc[-1]
    return {
        'vol_ratio': round(float(vol_ratio), 2),
        'vol_ma': float(vol_ma.iloc[-1]),
        'volume_surge': vol_ratio > 2.0,        # 量能爆发
        'price_vol_agree': price_up == vol_up,   # 量价齐升/齐跌
        'vol_diverge': not (price_up == vol_up), # 量价背离
    }


def compute_all_indicators(df: pd.DataFrame) -> Optional[TechnicalIndicators]:
    """根据日K线DataFrame计算全部技术指标"""
    if df is None or len(df) < 30:
        return None

    try:
        close = df['close']
        rsi = calculate_rsi(close)
        macd, macd_sig, macd_hist = calculate_macd(close)
        bb_upper, bb_mid, bb_lower = calculate_bollinger(close)
        atr = calculate_atr(df)
        stoch_k, stoch_d = calculate_stochastic(df)

        ema_7 = close.ewm(span=7, adjust=False).mean()
        ema_25 = close.ewm(span=25, adjust=False).mean()
        ema_99 = close.ewm(span=99, adjust=False).mean()
        vol_ma = df['volume'].rolling(20).mean()

        bb_width = (bb_upper - bb_lower) / bb_mid

        return TechnicalIndicators(
            rsi_14=round(float(rsi.iloc[-1]), 2),
            macd=round(float(macd.iloc[-1]), 6),
            macd_signal=round(float(macd_sig.iloc[-1]), 6),
            macd_hist=round(float(macd_hist.iloc[-1]), 6),
            bb_upper=round(float(bb_upper.iloc[-1]), 6),
            bb_middle=round(float(bb_mid.iloc[-1]), 6),
            bb_lower=round(float(bb_lower.iloc[-1]), 6),
            bb_width=round(float(bb_width.iloc[-1]), 4),
            ema_7=round(float(ema_7.iloc[-1]), 6),
            ema_25=round(float(ema_25.iloc[-1]), 6),
            ema_99=round(float(ema_99.iloc[-1]), 6),
            volume_ma=round(float(vol_ma.iloc[-1]), 2),
            atr=round(float(atr.iloc[-1]), 6),
            stoch_k=round(float(stoch_k.iloc[-1]), 2),
            stoch_d=round(float(stoch_d.iloc[-1]), 2),
        )
    except Exception as e:
        logger.warning(f"技术指标计算失败: {e}")
        return None


def generate_buy_sell_signal(
    price: float,
    indicators: TechnicalIndicators,
    df: pd.DataFrame
) -> BuySellSignal:
    """
    综合技术指标生成买卖信号
    信号强度：0-100
    """
    reasons = []
    score = 0
    signal = SignalType.HOLD

    if not indicators:
        return BuySellSignal(signal=SignalType.HOLD, strength=0, reasons=["指标数据不足"])

    # ---- RSI信号 ----
    rsi = indicators.rsi_14 or 50
    if rsi < 30:
        score += 25
        reasons.append(f"RSI极度超卖({rsi:.1f})")
    elif rsi < 40:
        score += 15
        reasons.append(f"RSI超卖({rsi:.1f})")
    elif rsi > 75:
        score -= 20
        reasons.append(f"RSI超买({rsi:.1f})")
    elif rsi > 65:
        score -= 10

    # ---- MACD信号 ----
    macd_h = indicators.macd_hist or 0
    macd = indicators.macd or 0
    if macd_h > 0 and macd > 0:
        score += 20
        reasons.append("MACD金叉上方")
    elif macd_h > 0 and macd < 0:
        score += 10
        reasons.append("MACD金叉(零轴下方)")
    elif macd_h < 0 and macd < 0:
        score -= 15
        reasons.append("MACD死叉下方")

    # ---- 布林带信号 ----
    bb_lower = indicators.bb_lower or 0
    bb_middle = indicators.bb_middle or 0
    bb_upper = indicators.bb_upper or 0
    bb_width = indicators.bb_width or 0.05

    if bb_lower > 0 and price <= bb_lower:
        score += 20
        reasons.append("触及布林下轨（超跌）")
    elif bb_lower > 0 and price <= bb_lower * 1.02:
        score += 10
        reasons.append("接近布林下轨")

    if price >= bb_upper:
        score -= 15
        reasons.append("触及布林上轨（超买）")

    # 布林带收缩（蓄力）
    if bb_width < 0.03 and bb_middle > 0:
        score += 10
        reasons.append("布林带收缩蓄力")

    # ---- EMA趋势 ----
    ema7 = indicators.ema_7 or 0
    ema25 = indicators.ema_25 or 0
    ema99 = indicators.ema_99 or 0
    if ema7 > ema25 > ema99:
        score += 15
        reasons.append("多头排列趋势")
    elif ema7 < ema25 < ema99:
        score -= 15
        reasons.append("空头排列趋势")

    # ---- KDJ信号 ----
    k = indicators.stoch_k or 50
    d = indicators.stoch_d or 50
    if k < 20 and d < 20:
        score += 15
        reasons.append(f"KDJ超卖区({k:.1f})")
    elif k > 80 and d > 80:
        score -= 10
        reasons.append(f"KDJ超买区({k:.1f})")

    # ---- 量能分析 ----
    if len(df) >= 20:
        vol_trend = calculate_volume_trend(df)
        if vol_trend['volume_surge']:
            score += 10
            reasons.append(f"成交量爆发({vol_trend['vol_ratio']}x均量)")
        if vol_trend['price_vol_agree'] and df['close'].iloc[-1] > df['close'].iloc[-2]:
            score += 8
            reasons.append("量价齐升")
        if vol_trend['vol_diverge']:
            score -= 5
            reasons.append("量价背离警告")

    # ---- 最终判断 ----
    if score >= 50:
        signal = SignalType.STRONG_BUY
    elif score >= 25:
        signal = SignalType.BUY
    elif score <= -30:
        signal = SignalType.STRONG_SELL
    elif score <= -10:
        signal = SignalType.SELL
    else:
        signal = SignalType.HOLD

    strength = min(100, max(0, 50 + score))

    # ---- 计算目标价和止损 ----
    atr = indicators.atr or (price * 0.03)
    entry_price = price
    stop_loss = round(price - 1.5 * atr, 8)
    tp1 = round(price * 1.05, 8)
    tp2 = round(price * 1.10, 8)
    tp3 = round(price * 1.20, 8)

    return BuySellSignal(
        signal=signal,
        strength=round(strength, 1),
        reasons=reasons,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
    )
