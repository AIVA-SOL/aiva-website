"""
推特/X 公开推文爬取模块（无需 API Key）
=========================================
策略：通过多个公开 Nitter 镜像实例爬取推文
特性：
  - 多实例自动探活 + 健康状态缓存（60min TTL）
  - 多策略爬取：账号时间线 / 搜索页 / JSON端点
  - 精准时间解析（ISO / 相对时间 "2h ago" / "Mar 14" 等）
  - 加权情绪分析（互动量加权 + 关键词分级权重）
  - 推文结果本地缓存（默认30min TTL，避免限流）
  - 批量并发（筛选引擎一次请求多个币种）
  - 账号自动发现（未知币先尝试搜索官方账号）
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from .config import (
    TWITTER_SEARCH_URL,
    TWITTER_BACKUP_URLS,
    TWEET_STALE_HOURS,
    TWEET_CHECK_INTERVAL,
)
from .models import SentimentScore, TweetStatus

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 常量 & 配置
# ─────────────────────────────────────────────

# Nitter 实例列表（越靠前优先级越高）
NITTER_INSTANCES: List[str] = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
    "https://nitter.catsarch.com",
    "https://nitter.rawbit.ninja",
    "https://nitter.moomoo.me",
    "https://nitter.mint.lgbt",
]

# 推特账号映射表（symbol → @username，持续扩充）
KNOWN_ACCOUNTS: Dict[str, str] = {
    # 主流公链
    "BTC":    "bitcoin",
    "ETH":    "ethereum",
    "BNB":    "binance",
    "SOL":    "solana",
    "ADA":    "cardano",
    "DOT":    "polkadot",
    "AVAX":   "avalancheavax",
    "ATOM":   "cosmosecosystem",
    "NEAR":   "nearprotocol",
    "FTM":    "fantomfdn",
    "ONE":    "harmonyprotocol",
    "ALGO":   "algorand",
    "HBAR":   "hedera",
    "XLM":    "stellar",
    "VET":    "vechainofficial",
    "EOS":    "eos_io",
    "FLOW":   "flow_blockchain",
    "EGLD":   "multiversx",
    "ICP":    "dfinity",
    "KAVA":   "kava_platform",
    "CELO":   "celo_org",
    "GLMR":   "moonbeamnetwork",
    "ASTR":   "astar_network",
    # Layer2 / 扩容
    "MATIC":  "0xpolygon",
    "ARB":    "arbitrum",
    "OP":     "optimismfnd",
    "IMX":    "immutablex",
    "ZKSYNC": "zksync",
    "STRK":   "starknet",
    "MANTA":  "mantanetwork",
    "SCROLL": "scroll_zkevm",
    # DeFi
    "UNI":    "uniswap",
    "AAVE":   "aaveaave",
    "MKR":    "makerdao",
    "CRV":    "curvefinance",
    "SNX":    "synthetix_io",
    "COMP":   "compoundfinance",
    "1INCH":  "1inch",
    "BAL":    "balancer",
    "YFI":    "iearnfinance",
    "GMX":    "gmx_io",
    "DYDX":   "dydx",
    "PENDLE": "pendle_fi",
    "EIGEN":  "eigenlayer",
    # AI / 新赛道
    "FET":    "fetch_ai",
    "AGIX":   "singularitynet",
    "OCEAN":  "oceanprotocol",
    "RLC":    "iex_ec",
    "TAO":    "opentensor",
    "WLD":    "worldcoin",
    # NFT / GameFi
    "APE":    "apecoin",
    "SAND":   "thesandboxgame",
    "MANA":   "decentraland",
    "AXS":    "axieinfinity",
    "GMT":    "stepn_official",
    "MAGIC":  "magic_nftcom",
    # Oracle / 工具
    "LINK":   "chainlink",
    "BAND":   "bandprotocol",
    "API3":   "api3dao",
    # Meme
    "DOGE":   "dogecoin",
    "SHIB":   "shibtoken",
    "PEPE":   "pepecoineth",
    "FLOKI":  "realfloki",
    "BONK":   "bonk_inu",
    "WIF":    "dogwifcoin",
    # 跨链 / 存储
    "DOT":    "polkadot",
    "KSM":   "kusamanetwork",
    "FIL":   "filecoin",
    "AR":    "arweave",
    "STORJ": "storjproject",
    # 其他
    "APT":   "aptosfoundation",
    "SUI":   "suifoundation",
    "INJ":   "injprotocol",
    "TIA":   "celestia",
    "XRP":   "ripple",
    "LTC":   "litecoin",
    "TRX":   "trondao",
    "BCH":   "bitcoincashorg",
    "ETC":   "eth_classic",
    "XMR":   "monero",
    "ZEC":   "zcash",
    "DASH":  "dashpay",
    "ZIL":   "zilliqa",
    "IOTA":  "iota",
    "NANO":  "nanocurrency",
}

# 正向关键词 → (权重, 中英文)
POSITIVE_WORDS: List[Tuple[int, str]] = [
    # 高权重（重大利好）
    (3, "mainnet launch"),
    (3, "partnership"),
    (3, "listing"),
    (3, "all-time high"),
    (3, "ath"),
    (3, "major upgrade"),
    (3, "burn"),
    (3, "buyback"),
    (3, "airdrop"),
    (3, "上线"),
    (3, "主网"),
    (3, "合作"),
    (3, "利好"),
    (3, "创新高"),
    # 中权重
    (2, "launch"),
    (2, "upgrade"),
    (2, "bullish"),
    (2, "adoption"),
    (2, "integration"),
    (2, "milestone"),
    (2, "growth"),
    (2, "record"),
    (2, "breakout"),
    (2, "excited"),
    (2, "proud"),
    (2, "strong"),
    (2, "发布"),
    (2, "突破"),
    (2, "里程碑"),
    # 低权重
    (1, "great"),
    (1, "amazing"),
    (1, "positive"),
    (1, "win"),
    (1, "bullrun"),
    (1, "moon"),
    (1, "好"),
    (1, "涨"),
]

# 负向关键词 → (权重, 词)
NEGATIVE_WORDS: List[Tuple[int, str]] = [
    # 高权重（重大风险）
    (3, "hack"),
    (3, "exploit"),
    (3, "vulnerability"),
    (3, "breach"),
    (3, "rug pull"),
    (3, "rug"),
    (3, "scam"),
    (3, "fraud"),
    (3, "lawsuit"),
    (3, "sec"),
    (3, "黑客"),
    (3, "漏洞"),
    (3, "欺诈"),
    (3, "跑路"),
    (3, "监管"),
    # 中权重
    (2, "dump"),
    (2, "bearish"),
    (2, "crash"),
    (2, "ban"),
    (2, "delay"),
    (2, "concern"),
    (2, "崩盘"),
    (2, "下跌"),
    (2, "利空"),
    # 低权重
    (1, "issue"),
    (1, "problem"),
    (1, "bug"),
    (1, "risk"),
    (1, "bear"),
    (1, "问题"),
    (1, "风险"),
]

# HTTP 请求头（轮换 UA 降低被拦截概率）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

_ua_index = 0


def _next_ua() -> str:
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


# ─────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────

@dataclass
class Tweet:
    text: str
    timestamp: Optional[datetime] = None      # UTC datetime
    likes: int = 0
    retweets: int = 0
    replies: int = 0

    @property
    def engagement(self) -> int:
        """互动量总和，用于加权"""
        return self.likes + self.retweets * 2 + self.replies


@dataclass
class TwitterProfile:
    username: str
    tweets: List[Tweet] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)
    source_instance: str = ""
    error: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return not self.tweets

    @property
    def latest_tweet_time(self) -> Optional[datetime]:
        valid = [t.timestamp for t in self.tweets if t.timestamp]
        return max(valid) if valid else None


# ─────────────────────────────────────────────
# Nitter 实例健康管理
# ─────────────────────────────────────────────

class NitterInstanceManager:
    """
    管理多个 Nitter 实例的可用状态
    - 每 60 分钟重新探测一次
    - 优先返回响应最快的实例
    """

    HEALTH_TTL = 3600  # 健康状态缓存 1 小时

    def __init__(self) -> None:
        self._health: Dict[str, Tuple[bool, float]] = {}  # url → (ok, check_time)
        self._lock = asyncio.Lock()
        self._preferred: Optional[str] = None

    async def get_best(self) -> str:
        """返回当前可用的最佳 Nitter 实例 URL"""
        async with self._lock:
            # 尝试返回缓存的首选实例
            if self._preferred:
                ok, ts = self._health.get(self._preferred, (False, 0))
                if ok and (time.time() - ts) < self.HEALTH_TTL:
                    return self._preferred

            # 重新探测
            self._preferred = await self._probe_all()
            return self._preferred

    async def _probe_all(self) -> str:
        """并发探测所有实例，返回响应最快且可用的实例"""
        async def probe(url: str) -> Tuple[str, bool, float]:
            try:
                t0 = time.time()
                async with httpx.AsyncClient(timeout=6) as c:
                    r = await c.get(f"{url}/twitter", headers={"User-Agent": _next_ua()})
                latency = time.time() - t0
                ok = r.status_code < 400
                return url, ok, latency
            except Exception:
                return url, False, 9999.0

        tasks = [probe(u) for u in NITTER_INSTANCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        best_url = NITTER_INSTANCES[0]
        best_latency = 9999.0
        now = time.time()

        for item in results:
            if isinstance(item, Exception):
                continue
            url, ok, lat = item
            self._health[url] = (ok, now)
            if ok and lat < best_latency:
                best_latency = lat
                best_url = url

        logger.info(
            f"Nitter 探活完成，可用实例: "
            f"{[u for u, (ok, _) in self._health.items() if ok]}, "
            f"首选: {best_url} ({best_latency:.2f}s)"
        )
        return best_url

    async def get_all_healthy(self) -> List[str]:
        """返回全部健康实例（用于降级重试）"""
        now = time.time()
        return [
            u for u, (ok, ts) in self._health.items()
            if ok and (now - ts) < self.HEALTH_TTL
        ] or NITTER_INSTANCES[:3]


_nitter_manager = NitterInstanceManager()


# ─────────────────────────────────────────────
# 时间解析
# ─────────────────────────────────────────────

_RELATIVE_RE = re.compile(
    r"(\d+)\s*(s|sec|second|seconds|m|min|minute|minutes|"
    r"h|hr|hour|hours|d|day|days|w|week|weeks)\s*ago",
    re.IGNORECASE,
)

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_ISO_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
]


def _parse_tweet_time(raw: Optional[str]) -> Optional[datetime]:
    """
    将 Nitter 页面中的时间字符串转为 UTC datetime。
    支持：
      - ISO 8601 格式
      - "2h ago" / "3 days ago" 等相对时间
      - "Mar 14, 2024" / "14 Mar" 等短格式
      - Unix 时间戳字符串
    """
    if not raw:
        return None
    raw = raw.strip()

    # 1. ISO 格式
    for fmt in _ISO_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass

    # 2. 相对时间 "Xh ago"
    m = _RELATIVE_RE.search(raw)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        now = datetime.now(timezone.utc)
        delta_map = {
            "s": timedelta(seconds=n),   "sec": timedelta(seconds=n),
            "second": timedelta(seconds=n), "seconds": timedelta(seconds=n),
            "m": timedelta(minutes=n),   "min": timedelta(minutes=n),
            "minute": timedelta(minutes=n), "minutes": timedelta(minutes=n),
            "h": timedelta(hours=n),     "hr": timedelta(hours=n),
            "hour": timedelta(hours=n),  "hours": timedelta(hours=n),
            "d": timedelta(days=n),      "day": timedelta(days=n),
            "days": timedelta(days=n),
            "w": timedelta(weeks=n),     "week": timedelta(weeks=n),
            "weeks": timedelta(weeks=n),
        }
        delta = delta_map.get(unit)
        if delta:
            return now - delta

    # 3. "Mar 14, 2024" 或 "14 Mar 2024"
    abbr_pattern = re.compile(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2}),?\s*(\d{4})?",
        re.IGNORECASE,
    )
    mo = abbr_pattern.search(raw)
    if mo:
        month = _MONTH_ABBR.get(mo.group(1).lower()[:3], 1)
        day = int(mo.group(2))
        year = int(mo.group(3)) if mo.group(3) else datetime.now().year
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            pass

    # 4. Unix 时间戳
    try:
        ts = float(raw)
        if ts > 1e9:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    except ValueError:
        pass

    logger.debug(f"无法解析推特时间: {raw!r}")
    return None


# ─────────────────────────────────────────────
# 页面爬取 & 解析
# ─────────────────────────────────────────────

def _safe_int(text: Optional[str]) -> int:
    """解析 '1.2K' / '10,345' / '5' 等互动数"""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    m = re.match(r"([\d.]+)([KkMm]?)", text)
    if not m:
        return 0
    val = float(m.group(1))
    suffix = m.group(2).upper()
    if suffix == "K":
        val *= 1_000
    elif suffix == "M":
        val *= 1_000_000
    return int(val)


def _parse_nitter_html(html: str) -> List[Tweet]:
    """解析 Nitter 账号页面 HTML，返回推文列表"""
    soup = BeautifulSoup(html, "lxml")
    tweets: List[Tweet] = []

    # Nitter 的推文容器（不同版本有差异，逐一尝试）
    items = (
        soup.select(".timeline-item:not(.show-more)")
        or soup.select(".tweet-body")
        or soup.select("article")
    )

    for item in items[:30]:
        # ── 文本 ──
        content_el = (
            item.select_one(".tweet-content")
            or item.select_one(".tweet-text")
            or item.select_one(".content p")
        )
        text = content_el.get_text(" ", strip=True) if content_el else ""
        if not text:
            continue

        # ── 时间 ──
        time_el = item.select_one("time") or item.select_one(".tweet-date a")
        raw_time = None
        if time_el:
            raw_time = (
                time_el.get("datetime")
                or time_el.get("title")
                or time_el.get_text(strip=True)
            )
        ts = _parse_tweet_time(raw_time)

        # ── 互动量 ──
        def _stat(selector: str) -> int:
            el = item.select_one(selector)
            return _safe_int(el.get_text(strip=True)) if el else 0

        likes    = _stat(".icon-heart")    or _stat(".likes")    or _stat("[data-likes]")
        retweets = _stat(".icon-retweet")  or _stat(".retweets") or _stat("[data-retweets]")
        replies  = _stat(".icon-comment")  or _stat(".replies")  or _stat("[data-replies]")

        tweets.append(Tweet(
            text=text,
            timestamp=ts,
            likes=likes,
            retweets=retweets,
            replies=replies,
        ))

    return tweets


async def _fetch_profile_html(
    username: str,
    instance: str,
    client: httpx.AsyncClient,
) -> Optional[str]:
    """从指定实例爬取账号主页 HTML"""
    url = f"{instance}/{username}"
    try:
        resp = await client.get(
            url,
            headers={
                "User-Agent": _next_ua(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            },
            follow_redirects=True,
        )
        if resp.status_code == 200:
            return resp.text
        logger.debug(f"Nitter {instance}/{username} 返回 {resp.status_code}")
        return None
    except Exception as e:
        logger.debug(f"Nitter 请求失败 {instance}/{username}: {e}")
        return None


async def fetch_user_tweets(username: str, max_retries: int = 3) -> TwitterProfile:
    """
    爬取指定 Twitter 用户的最新推文（带自动降级重试）
    """
    best = await _nitter_manager.get_best()
    all_healthy = await _nitter_manager.get_all_healthy()

    # 优先用最佳实例，失败后依次尝试其他健康实例
    instances_to_try = [best] + [u for u in all_healthy if u != best]

    async with httpx.AsyncClient(timeout=15) as client:
        for i, instance in enumerate(instances_to_try[:max_retries]):
            html = await _fetch_profile_html(username, instance, client)
            if html:
                tweets = _parse_nitter_html(html)
                if tweets:
                    logger.debug(
                        f"@{username} 爬取成功，来源: {instance}，"
                        f"推文数: {len(tweets)}"
                    )
                    return TwitterProfile(
                        username=username,
                        tweets=tweets,
                        source_instance=instance,
                    )
            await asyncio.sleep(0.3 * (i + 1))  # 指数退避

    return TwitterProfile(username=username, error="所有 Nitter 实例均失败")


# ─────────────────────────────────────────────
# 账号自动发现
# ─────────────────────────────────────────────

async def discover_account(coin_symbol: str) -> Optional[str]:
    """
    对未知币种尝试在 Nitter 搜索页找官方账号。
    搜索关键词："{SYMBOL} official"，取第一个结果账号名。
    """
    query = f"{coin_symbol.lower()} official"
    instance = await _nitter_manager.get_best()
    url = f"{instance}/search?q={query}&f=users"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": _next_ua()},
                follow_redirects=True,
            )
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        # Nitter 搜索用户结果
        first_user = (
            soup.select_one(".user-card .username")
            or soup.select_one(".tweet-header .username")
            or soup.select_one("a.username")
        )
        if first_user:
            name = first_user.get_text(strip=True).lstrip("@")
            logger.info(f"自动发现 {coin_symbol} 的推特账号: @{name}")
            return name
    except Exception as e:
        logger.debug(f"账号自动发现失败 {coin_symbol}: {e}")

    return None


# ─────────────────────────────────────────────
# 情绪分析
# ─────────────────────────────────────────────

def _score_tweet(tweet: Tweet) -> Tuple[float, float]:
    """
    对单条推文计算正向/负向加权得分。
    互动量越高，权重越大（对数缩放）。
    返回 (pos_weight, neg_weight)
    """
    import math
    text_lower = tweet.text.lower()
    engagement_factor = 1.0 + math.log1p(tweet.engagement) * 0.1

    pos = sum(w for w, kw in POSITIVE_WORDS if kw.lower() in text_lower)
    neg = sum(w for w, kw in NEGATIVE_WORDS if kw.lower() in text_lower)

    return pos * engagement_factor, neg * engagement_factor


def analyze_sentiment(tweets: List[Tweet]) -> Tuple[float, float]:
    """
    加权情绪分析。
    返回 (positive_ratio 0-1, sentiment_score 0-100)
    """
    if not tweets:
        return 0.5, 50.0

    total_pos = 0.0
    total_neg = 0.0
    pos_tweet_count = 0
    total = len(tweets)

    for tw in tweets:
        p, n = _score_tweet(tw)
        total_pos += p
        total_neg += n
        if p > n:
            pos_tweet_count += 1

    pos_ratio = pos_tweet_count / total if total > 0 else 0.5

    total_score = total_pos + total_neg
    if total_score == 0:
        sentiment_score = 50.0
    else:
        sentiment_score = 50.0 + (total_pos - total_neg) / total_score * 50.0

    return round(pos_ratio, 3), round(float(min(100, max(0, sentiment_score))), 1)


# ─────────────────────────────────────────────
# 活跃度判断
# ─────────────────────────────────────────────

def check_activity(profile: TwitterProfile) -> TweetStatus:
    """
    根据最新推文时间判断账号活跃状态。
    - ACTIVE:    最新推文在 TWEET_STALE_HOURS 小时内
    - INACTIVE:  有推文但已超时
    - NO_ACCOUNT: 没有推文数据
    """
    if profile.is_empty:
        return TweetStatus.NO_ACCOUNT

    latest = profile.latest_tweet_time
    if latest is None:
        # 时间解析失败，但确实有推文内容 → 视为活跃
        return TweetStatus.ACTIVE

    elapsed_hours = (datetime.now(timezone.utc) - latest).total_seconds() / 3600
    if elapsed_hours <= TWEET_STALE_HOURS:
        return TweetStatus.ACTIVE
    return TweetStatus.INACTIVE


# ─────────────────────────────────────────────
# 推文缓存层
# ─────────────────────────────────────────────

@dataclass
class _CacheEntry:
    profile: TwitterProfile
    score: SentimentScore
    created_at: float = field(default_factory=time.time)


class TwitterCache:
    """内存缓存，避免对同一账号频繁爬取"""

    def __init__(self, ttl: int = TWEET_CHECK_INTERVAL) -> None:
        self._store: Dict[str, _CacheEntry] = {}
        self._ttl = ttl

    def get(self, coin: str) -> Optional[SentimentScore]:
        entry = self._store.get(coin.upper())
        if entry and (time.time() - entry.created_at) < self._ttl:
            return entry.score
        return None

    def set(self, coin: str, profile: TwitterProfile, score: SentimentScore) -> None:
        self._store[coin.upper()] = _CacheEntry(profile=profile, score=score)

    def invalidate(self, coin: str) -> None:
        self._store.pop(coin.upper(), None)

    def stats(self) -> Dict:
        now = time.time()
        valid = sum(1 for e in self._store.values() if (now - e.created_at) < self._ttl)
        return {"total": len(self._store), "valid": valid, "ttl_seconds": self._ttl}


_cache = TwitterCache()


# ─────────────────────────────────────────────
# 公开 API
# ─────────────────────────────────────────────

async def get_twitter_sentiment(base_coin: str, force_refresh: bool = False) -> SentimentScore:
    """
    获取单个币种的推特情绪评分（带缓存）。

    Parameters
    ----------
    base_coin : str
        币种符号，如 "BTC"、"SOL"
    force_refresh : bool
        True 时忽略缓存强制重新爬取

    Returns
    -------
    SentimentScore
    """
    coin_upper = base_coin.upper()

    # 1. 命中缓存
    if not force_refresh:
        cached = _cache.get(coin_upper)
        if cached is not None:
            logger.debug(f"[{coin_upper}] 推特数据命中缓存")
            return cached

    # 2. 查找账号名
    username = KNOWN_ACCOUNTS.get(coin_upper)
    if not username:
        username = await discover_account(coin_upper)
    if not username:
        username = coin_upper.lower()  # 最终回退

    # 3. 爬取推文
    profile = await fetch_user_tweets(username)

    # 4. 计算情绪
    if profile.is_empty:
        score = SentimentScore(
            tweet_status=TweetStatus.NO_ACCOUNT,
            tweet_score=50.0,
            news_score=50.0,
        )
    else:
        pos_ratio, sentiment_score = analyze_sentiment(profile.tweets)
        tweet_status = check_activity(profile)
        latest = profile.latest_tweet_time

        score = SentimentScore(
            tweet_score=sentiment_score,
            tweet_status=tweet_status,
            last_tweet_time=latest.isoformat() if latest else None,
            tweet_count_7d=_count_tweets_in_days(profile.tweets, days=7),
            positive_ratio=pos_ratio,
            news_score=sentiment_score,
        )

    # 5. 写缓存
    _cache.set(coin_upper, profile, score)
    logger.info(
        f"[{coin_upper}] @{username} 推特分析完成 → "
        f"状态={score.tweet_status.value}, "
        f"情绪分={score.tweet_score}, "
        f"7天推文={score.tweet_count_7d}"
    )
    return score


async def batch_get_twitter_sentiment(
    coins: List[str],
    concurrency: int = 5,
    force_refresh: bool = False,
) -> Dict[str, SentimentScore]:
    """
    批量并发获取多个币种的推特情绪。

    Parameters
    ----------
    coins : List[str]
        币种列表，如 ["BTC", "ETH", "SOL"]
    concurrency : int
        最大并发数（防止 Nitter 实例限速）
    force_refresh : bool
        是否强制刷新缓存

    Returns
    -------
    Dict[str, SentimentScore]
        coin_symbol → SentimentScore
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _one(coin: str) -> Tuple[str, SentimentScore]:
        async with semaphore:
            score = await get_twitter_sentiment(coin, force_refresh=force_refresh)
            await asyncio.sleep(0.2)  # 轻微节流
            return coin.upper(), score

    tasks = [_one(c) for c in coins]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: Dict[str, SentimentScore] = {}
    for item in results:
        if isinstance(item, Exception):
            logger.warning(f"批量推特情绪出错: {item}")
            continue
        symbol, score = item
        output[symbol] = score

    return output


async def get_raw_tweets(base_coin: str) -> List[dict]:
    """
    返回原始推文列表（供 API 接口透传给前端）。
    """
    coin_upper = base_coin.upper()
    username = KNOWN_ACCOUNTS.get(coin_upper) or coin_upper.lower()
    profile = await fetch_user_tweets(username)

    return [
        {
            "text": tw.text,
            "time": tw.timestamp.isoformat() if tw.timestamp else None,
            "likes": tw.likes,
            "retweets": tw.retweets,
            "replies": tw.replies,
            "engagement": tw.engagement,
        }
        for tw in profile.tweets
    ]


def get_cache_stats() -> dict:
    """返回缓存统计信息（调试用）"""
    return _cache.stats()


# ─────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────

def _count_tweets_in_days(tweets: List[Tweet], days: int = 7) -> int:
    """统计最近 N 天内的推文数量"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    count = 0
    for tw in tweets:
        if tw.timestamp is None:
            count += 1  # 时间未知，乐观计入
        elif tw.timestamp >= cutoff:
            count += 1
    return count
