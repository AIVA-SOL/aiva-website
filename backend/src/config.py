"""
全局配置文件
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ============ 交易所配置 ============
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
GATE_API_KEY = os.getenv("GATE_API_KEY", "")
GATE_SECRET_KEY = os.getenv("GATE_SECRET_KEY", "")

# ============ 筛选参数 ============
# 目标涨幅（5-10天内，最低20%）
TARGET_GAIN_MIN = 20.0
FORECAST_DAYS = 7  # 预测天数

# 价格区间（低价币，USDT计价）
PRICE_MAX = 1.0        # 最高价格上限
PRICE_MIN = 0.000001   # 最低价格下限

# 市值过滤（排除过小山寨币，单位 USDT）
MARKET_CAP_MIN = 5_000_000   # 最低500万
MARKET_CAP_MAX = 500_000_000  # 最高5亿（中小盘）

# 24h成交量最低要求（USDT）
VOLUME_MIN = 1_000_000  # 100万

# 风险系数阈值（0-1，越小越安全）
RISK_SCORE_MAX = 0.5

# ============ 技术指标参数 ============
RSI_OVERSOLD = 35      # RSI超卖阈值（低于此值视为超卖）
RSI_OVERBOUGHT = 70    # RSI超买阈值
MACD_SIGNAL_THRESHOLD = 0.0
BB_SQUEEZE_FACTOR = 0.02  # 布林带收缩因子

# ============ 数据源配置 ============
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
BINANCE_REST_URL = "https://api.binance.com"
GATE_REST_URL = "https://api.gateio.ws/api/v4"
GATE_WS_URL = "wss://api.gateio.ws/ws/v4/"

# ============ 缓存配置 ============
CACHE_TTL = 30  # 秒
REALTIME_INTERVAL = 5  # 实时数据刷新间隔（秒）
SCREEN_INTERVAL = 300  # 筛选刷新间隔（秒）

# ============ 推特爬取配置 ============
TWITTER_SEARCH_URL = "https://nitter.poast.org"  # Nitter实例
TWITTER_BACKUP_URLS = [
    "https://nitter.privacydev.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]
TWEET_CHECK_INTERVAL = 3600  # 推特检查间隔（秒）
TWEET_STALE_HOURS = 48       # 超过48小时无推文视为不活跃

# ============ 回测参数 ============
BACKTEST_YEARS = 3
BACKTEST_INTERVAL = "1d"

# ============ Web服务配置 ============
API_HOST = "0.0.0.0"
API_PORT = 8000
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5500",   # VS Code Live Server
    "http://127.0.0.1:5500",
    "null",                    # file:// 本地打开时 Origin 为 "null"
    "*",                       # 开发环境全放开（生产环境请删除）
]
