"""
买卖点信号引擎 — 独立模块
支持：多时框架共振确认、动态止盈止损、信号强度打分
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from .indicators import (
    calculate_rsi,
    calculate_macd,
    calculate_bollinger,
    calculate_atr,
    calculate_stochastic,
    calculate_volume_trend,
)
from .models import BuySellSignal, SignalType, TechnicalIndicators

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 单时框信号
# ─────────────────────────────────────────────

@dataclass
class _FrameSignal:
    timeframe: str
    score: float          # -100 ~ +100
    reasons: List[str]


def _analyze_frame(df: pd.DataFrame, tf_label: str) -> _FrameSignal:
    """对单个时间框架的K线数据打分"""
    if df is None or len(df) < 30:
        return _FrameSignal(tf_label, 0.0, [])

    close = df["close"]
    score = 0.0
    reasons: List[str] = []

    # RSI
    rsi = calculate_rsi(close)
    r = float(rsi.iloc[-1])
    if r < 28:
        score += 30; reasons.append(f"RSI极度超卖 {r:.1f}")
    elif r < 38:
        score += 18; reasons.append(f"RSI超卖 {r:.1f}")
    elif r > 72:
        score -= 25; reasons.append(f"RSI超买 {r:.1f}")
    elif r > 62:
        score -= 12

    # MACD
    macd, sig, hist = calculate_macd(close)
    h_now, h_prev = float(hist.iloc[-1]), float(hist.iloc[-2])
    m_now = float(macd.iloc[-1])
    if h_prev < 0 <= h_now:                  # 金叉
        if m_now < 0:
            score += 20; reasons.append(f"MACD零轴下金叉({tf_label})")
        else:
            score += 12; reasons.append(f"MACD零轴上金叉({tf_label})")
    elif h_prev > 0 >= h_now:                 # 死叉
        score -= 20; reasons.append(f"MACD死叉({tf_label})")
    elif h_now > 0 and m_now > 0:
        score += 8

    # 布林带
    bb_u, bb_m, bb_l = calculate_bollinger(close)
    price = float(close.iloc[-1])
    if float(bb_l.iloc[-1]) > 0:
        if price <= float(bb_l.iloc[-1]):
            score += 20; reasons.append(f"触及布林下轨({tf_label})")
        elif price >= float(bb_u.iloc[-1]):
            score -= 18; reasons.append(f"触及布林上轨({tf_label})")

    # EMA 多空排列
    ema7  = float(close.ewm(span=7,  adjust=False).mean().iloc[-1])
    ema25 = float(close.ewm(span=25, adjust=False).mean().iloc[-1])
    ema99 = float(close.ewm(span=99, adjust=False).mean().iloc[-1])
    if ema7 > ema25 > ema99:
        score += 12; reasons.append(f"多头排列({tf_label})")
    elif ema7 < ema25 < ema99:
        score -= 12; reasons.append(f"空头排列({tf_label})")

    # KDJ
    k, d = calculate_stochastic(df)
    kv, dv = float(k.iloc[-1]), float(d.iloc[-1])
    k_prev = float(k.iloc[-2])
    if kv < 20:
        score += 12; reasons.append(f"KDJ超卖({tf_label})")
    elif kv > 80:
        score -= 10
    if k_prev < dv <= kv:                    # K上穿D
        score += 8; reasons.append(f"KDJ金叉({tf_label})")

    # 量能
    vol = calculate_volume_trend(df)
    if vol["volume_surge"] and float(close.iloc[-1]) > float(close.iloc[-2]):
        score += 10; reasons.append(f"量价齐升({tf_label})")
    if vol["vol_diverge"]:
        score -= 5

    return _FrameSignal(tf_label, max(-100, min(100, score)), reasons)


# ─────────────────────────────────────────────
# 多时框共振确认
# ─────────────────────────────────────────────

# 各时间框架权重（日线最重）
_TF_WEIGHTS = {"1d": 0.50, "4h": 0.30, "1h": 0.20}


def generate_signal_multi_tf(
    price: float,
    multi_df: Dict[str, pd.DataFrame],
) -> BuySellSignal:
    """
    多时框架共振信号。

    Parameters
    ----------
    price : float
        当前实时价格
    multi_df : dict
        {"1d": DataFrame, "4h": DataFrame, "1h": DataFrame}
    """
    frame_signals: List[_FrameSignal] = []
    all_reasons: List[str] = []

    for tf, weight in _TF_WEIGHTS.items():
        df = multi_df.get(tf)
        if df is not None and not df.empty:
            fs = _analyze_frame(df, tf)
            frame_signals.append(fs)
            all_reasons.extend(fs.reasons)

    if not frame_signals:
        return BuySellSignal(signal=SignalType.HOLD, strength=0, reasons=["数据不足"])

    # 加权总分
    total_score = sum(
        fs.score * _TF_WEIGHTS.get(fs.timeframe, 0.3)
        for fs in frame_signals
    )

    # 检查多时框共振（同向加分）
    directions = [fs.score > 0 for fs in frame_signals]
    if all(directions):
        total_score *= 1.2          # 多框共振放大 20%
        all_reasons.insert(0, "多时框共振看多")
    elif not any(directions):
        total_score *= 1.2
        all_reasons.insert(0, "多时框共振看空")

    # 计算 ATR 用于动态止盈止损
    best_df = multi_df.get("1d") or multi_df.get("4h") or next(iter(multi_df.values()))
    atr_val = float(calculate_atr(best_df).iloc[-1]) if best_df is not None and not best_df.empty else price * 0.03

    # 信号判定
    if total_score >= 45:
        signal = SignalType.STRONG_BUY
    elif total_score >= 20:
        signal = SignalType.BUY
    elif total_score <= -45:
        signal = SignalType.STRONG_SELL
    elif total_score <= -20:
        signal = SignalType.SELL
    else:
        signal = SignalType.HOLD

    strength = min(100.0, max(0.0, 50.0 + total_score))

    # 动态止盈止损（基于 ATR）
    atr_mult = {
        SignalType.STRONG_BUY: (1.2, 1.8, 2.5, 4.0),
        SignalType.BUY:        (1.5, 1.5, 2.0, 3.0),
        SignalType.HOLD:       (2.0, 0,   0,   0),
        SignalType.SELL:       (1.5, 0,   0,   0),
        SignalType.STRONG_SELL:(1.2, 0,   0,   0),
    }
    sl_m, tp1_m, tp2_m, tp3_m = atr_mult[signal]

    stop_loss   = round(price - sl_m  * atr_val, 8)
    tp1 = round(price + tp1_m * atr_val, 8) if tp1_m else None
    tp2 = round(price + tp2_m * atr_val, 8) if tp2_m else None
    tp3 = round(price + tp3_m * atr_val, 8) if tp3_m else None

    return BuySellSignal(
        signal=signal,
        strength=round(strength, 1),
        reasons=all_reasons[:10],          # 最多10条原因
        entry_price=price,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
    )


# ─────────────────────────────────────────────
# 单时框快速信号（screener 内部用）
# ─────────────────────────────────────────────

def quick_signal(price: float, df: pd.DataFrame) -> BuySellSignal:
    """
    仅用日线数据快速生成信号（筛选引擎批量处理用，速度优先）
    """
    fs = _analyze_frame(df, "1d")
    score = fs.score

    if score >= 40:
        signal = SignalType.STRONG_BUY
    elif score >= 18:
        signal = SignalType.BUY
    elif score <= -40:
        signal = SignalType.STRONG_SELL
    elif score <= -18:
        signal = SignalType.SELL
    else:
        signal = SignalType.HOLD

    strength = min(100.0, max(0.0, 50.0 + score))

    atr_val = float(calculate_atr(df).iloc[-1]) if len(df) > 14 else price * 0.03
    return BuySellSignal(
        signal=signal,
        strength=round(strength, 1),
        reasons=fs.reasons[:8],
        entry_price=price,
        stop_loss=round(price - 1.5 * atr_val, 8),
        take_profit_1=round(price * 1.05, 8),
        take_profit_2=round(price * 1.10, 8),
        take_profit_3=round(price * 1.20, 8),
    )
