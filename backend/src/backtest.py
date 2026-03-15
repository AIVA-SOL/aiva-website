"""
3年历史数据回测模块
验证筛选信号的历史胜率、收益率、最大回撤等
"""
import numpy as np
import pandas as pd
from typing import Optional
from .models import BacktestResult
from .indicators import calculate_rsi, calculate_macd, calculate_bollinger
import logging

logger = logging.getLogger(__name__)


def backtest_strategy(df: pd.DataFrame) -> BacktestResult:
    """
    基于3年历史K线进行策略回测
    策略：RSI超卖 + MACD金叉 + 布林下轨 = 买入信号
    持有7天后检验涨幅
    """
    if df is None or len(df) < 60:
        return BacktestResult()

    try:
        close = df['close'].copy()

        # 计算指标
        rsi = calculate_rsi(close)
        macd, macd_sig, macd_hist = calculate_macd(close)
        bb_upper, bb_mid, bb_lower = calculate_bollinger(close)

        signals = []
        wins = 0
        total_gain = 0.0
        max_dd = 0.0

        for i in range(26, len(df) - 10):
            # 买入条件
            rsi_val = rsi.iloc[i]
            macd_cross = (macd_hist.iloc[i] > 0 and macd_hist.iloc[i-1] <= 0)
            bb_touch = close.iloc[i] <= bb_lower.iloc[i] * 1.02

            if rsi_val < 40 and macd_cross and bb_touch:
                entry = close.iloc[i]
                # 持有7天后平仓
                exit_price = close.iloc[min(i + 7, len(df) - 1)]
                gain_pct = (exit_price - entry) / entry * 100

                # 计算持有期间最大回撤
                holding_lows = df['low'].iloc[i:i+8]
                dd = (holding_lows.min() - entry) / entry * 100
                max_dd = min(max_dd, dd)

                signals.append(gain_pct)
                if gain_pct > 0:
                    wins += 1
                total_gain += gain_pct

        if not signals:
            return BacktestResult()

        win_rate = wins / len(signals) * 100
        avg_gain = total_gain / len(signals)

        # 夏普比率简化计算（收益均值/收益标准差）
        gains_arr = np.array(signals)
        sharpe = gains_arr.mean() / (gains_arr.std() + 1e-6) * np.sqrt(52)

        return BacktestResult(
            win_rate=round(win_rate, 1),
            avg_gain=round(avg_gain, 2),
            max_drawdown=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 2),
            signal_count=len(signals),
            profitable_signals=wins,
        )

    except Exception as e:
        logger.warning(f"回测失败: {e}")
        return BacktestResult()


def predict_gain(
    df: pd.DataFrame,
    days: int = 7
) -> float:
    """
    预测未来N天涨幅（线性回归 + 动量预测）
    返回预测涨幅百分比
    """
    if df is None or len(df) < 30:
        return 0.0

    try:
        close = df['close'].copy()
        n = min(30, len(close))
        recent = close.tail(n).values

        # 计算近期动量
        momentum_7 = (recent[-1] - recent[-7]) / recent[-7] * 100 if len(recent) >= 7 else 0
        momentum_14 = (recent[-1] - recent[-14]) / recent[-14] * 100 if len(recent) >= 14 else 0
        momentum_30 = (recent[-1] - recent[-30]) / recent[-30] * 100 if len(recent) >= 30 else 0

        # RSI修正
        rsi = calculate_rsi(close)
        rsi_latest = rsi.iloc[-1]
        rsi_factor = 1.0
        if rsi_latest < 30:
            rsi_factor = 1.5  # 超卖反弹预期放大
        elif rsi_latest < 40:
            rsi_factor = 1.2
        elif rsi_latest > 70:
            rsi_factor = 0.5  # 超买预期压缩

        # 线性回归斜率（趋势外推）
        x = np.arange(n)
        slope = np.polyfit(x, recent, 1)[0]
        slope_pct = slope / recent[-1] * 100 * days

        # 综合预测
        prediction = (
            momentum_7 * 0.3 +
            momentum_14 * 0.2 +
            slope_pct * 0.5
        ) * rsi_factor

        # 约束在合理范围
        return round(float(np.clip(prediction, -50, 150)), 2)

    except Exception as e:
        logger.warning(f"涨幅预测失败: {e}")
        return 0.0
