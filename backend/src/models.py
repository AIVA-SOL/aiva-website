"""
数据模型定义
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    STRONG_BUY = "STRONG_BUY"
    STRONG_SELL = "STRONG_SELL"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TweetStatus(str, Enum):
    ACTIVE = "ACTIVE"      # 正常更新
    INACTIVE = "INACTIVE"  # 超过48h未更新
    NO_ACCOUNT = "NO_ACCOUNT"  # 无官方推特


class CryptoBasic(BaseModel):
    symbol: str           # 交易对，如 BTC/USDT
    base: str             # 基础币种，如 BTC
    exchange: str         # 交易所来源
    price: float          # 当前价格（USDT）
    price_change_24h: float  # 24h涨跌幅（%）
    volume_24h: float     # 24h成交量（USDT）
    market_cap: Optional[float] = None  # 市值
    high_24h: float = 0
    low_24h: float = 0


class TechnicalIndicators(BaseModel):
    rsi_14: Optional[float] = None    # RSI(14)
    macd: Optional[float] = None      # MACD值
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    bb_upper: Optional[float] = None  # 布林上轨
    bb_middle: Optional[float] = None # 布林中轨
    bb_lower: Optional[float] = None  # 布林下轨
    bb_width: Optional[float] = None  # 布林带宽
    ema_7: Optional[float] = None
    ema_25: Optional[float] = None
    ema_99: Optional[float] = None
    volume_ma: Optional[float] = None # 成交量均线
    atr: Optional[float] = None       # ATR波动率
    stoch_k: Optional[float] = None   # KDJ
    stoch_d: Optional[float] = None


class SentimentScore(BaseModel):
    tweet_score: float = 0.0      # 推特情绪分（0-100）
    tweet_status: TweetStatus = TweetStatus.NO_ACCOUNT
    last_tweet_time: Optional[str] = None
    tweet_count_7d: int = 0       # 7天推文数
    positive_ratio: float = 0.0   # 正面推文比例
    news_score: float = 50.0      # 新闻热度分


class BacktestResult(BaseModel):
    win_rate: float = 0.0         # 胜率
    avg_gain: float = 0.0         # 平均涨幅
    max_drawdown: float = 0.0     # 最大回撤
    sharpe_ratio: float = 0.0     # 夏普比率
    signal_count: int = 0         # 信号次数（3年）
    profitable_signals: int = 0   # 盈利信号次数


class RiskMetrics(BaseModel):
    risk_score: float = 0.5       # 风险综合评分（0-1，越小越安全）
    risk_level: RiskLevel = RiskLevel.MEDIUM
    volatility_30d: float = 0.0   # 30日波动率
    liquidity_score: float = 0.5  # 流动性评分
    correlation_btc: float = 0.0  # 与BTC相关性
    pump_dump_risk: float = 0.0   # 拉盘砸盘风险


class BuySellSignal(BaseModel):
    signal: SignalType = SignalType.HOLD
    strength: float = 0.0         # 信号强度（0-100）
    reasons: List[str] = []       # 触发原因
    entry_price: Optional[float] = None   # 建议入场价
    stop_loss: Optional[float] = None     # 止损价
    take_profit_1: Optional[float] = None # 第一目标价
    take_profit_2: Optional[float] = None # 第二目标价
    take_profit_3: Optional[float] = None # 第三目标价
    signal_time: str = Field(default_factory=lambda: datetime.now().isoformat())


class CryptoScreenResult(BaseModel):
    """筛选结果主模型"""
    symbol: str
    base: str
    exchange: str
    price: float
    price_change_24h: float
    volume_24h: float
    market_cap: Optional[float] = None

    # 预测
    predicted_gain_5d: float = 0.0   # 5日预测涨幅
    predicted_gain_10d: float = 0.0  # 10日预测涨幅
    score: float = 0.0               # 综合评分（0-100）

    # 详细数据
    technicals: Optional[TechnicalIndicators] = None
    sentiment: Optional[SentimentScore] = None
    backtest: Optional[BacktestResult] = None
    risk: Optional[RiskMetrics] = None
    signal: Optional[BuySellSignal] = None

    # 元数据
    screened_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    tags: List[str] = []  # 标签，如 ["超卖反弹", "量价齐升", "推特活跃"]


class RealtimeQuote(BaseModel):
    """实时报价"""
    symbol: str
    exchange: str
    price: float
    change_24h: float
    volume_24h: float
    timestamp: float
    bid: Optional[float] = None
    ask: Optional[float] = None


class ScreenFilter(BaseModel):
    """筛选过滤条件"""
    price_max: float = 1.0
    price_min: float = 0.0
    min_predicted_gain: float = 20.0
    max_risk_score: float = 0.5
    min_volume: float = 1_000_000
    exchanges: List[str] = ["binance", "gate"]
    require_active_twitter: bool = False
    min_score: float = 60.0
