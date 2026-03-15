"""
合约地址查询模块
使用 CoinGecko 免费 API 获取币种在各链上的合约地址
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

# 内存缓存：{ "BTC": {"eth": "0x...", "bsc": "0x...", ...}, ... }
_contract_cache: Dict[str, Dict] = {}
_cache_expire: Dict[str, float] = {}
CACHE_TTL = 86400  # 24小时缓存（合约地址基本不变）

# 链名映射：CoinGecko platform id → 显示名称
PLATFORM_DISPLAY = {
    "ethereum":            "ETH",
    "binance-smart-chain": "BSC",
    "solana":              "SOL",
    "polygon-pos":         "MATIC",
    "arbitrum-one":        "ARB",
    "optimistic-ethereum": "OP",
    "base":                "BASE",
    "tron":                "TRX",
    "avalanche":           "AVAX",
    "fantom":              "FTM",
    "sui":                 "SUI",
    "aptos":               "APT",
    "ton":                 "TON",
}

# 优先显示的链顺序
PLATFORM_PRIORITY = [
    "ethereum", "binance-smart-chain", "solana", "tron",
    "polygon-pos", "arbitrum-one", "optimistic-ethereum",
    "base", "avalanche", "fantom", "sui", "aptos", "ton",
]

# 已知无合约地址的原生币（不需要查）
NATIVE_COINS = {"BTC", "ETH", "BNB", "SOL", "TRX", "ADA", "DOT", "AVAX", "MATIC", "ATOM"}

# CoinGecko coin id 快速映射（避免 search 请求，提高命中率）
KNOWN_COINGECKO_IDS: Dict[str, str] = {
    "PEPE": "pepe", "BONK": "bonk", "WIF": "dogwifcoin",
    "SHIB": "shiba-inu", "DOGE": "dogecoin", "ARB": "arbitrum",
    "OP": "optimism", "INJ": "injective-protocol", "TIA": "celestia",
    "NEAR": "near", "SUI": "sui", "APT": "aptos", "RNDR": "render-token",
    "FET": "fetch-ai", "AGIX": "singularitynet", "OCEAN": "ocean-protocol",
    "BLUR": "blur", "LDO": "lido-dao", "RPL": "rocket-pool",
    "SUSHI": "sushi", "UNI": "uniswap", "AAVE": "aave",
    "LINK": "chainlink", "GRT": "the-graph", "SNX": "synthetix-network-token",
    "CRV": "curve-dao-token", "COMP": "compound-governance-token",
    "MKR": "maker", "IMX": "immutable-x", "MANA": "decentraland",
    "SAND": "the-sandbox", "AXS": "axie-infinity",
    "FLOKI": "floki", "BABYDOGE": "baby-doge-coin",
    "TURBO": "turbo", "BRETT": "brett-based", "MOG": "mog-coin",
    "NOT": "notcoin", "TON": "the-open-network",
    "JTO": "jito-governance-token", "PYTH": "pyth-network",
    "JUP": "jupiter-exchange-solana", "RAY": "raydium",
    "ORCA": "orca", "MNGO": "mango-markets",
}


async def get_contract_addresses(coin_symbol: str) -> Dict[str, str]:
    """
    查询币种在各链上的合约地址。
    返回格式：{ "ETH": "0x...", "BSC": "0x...", "SOL": "..." }
    """
    symbol = coin_symbol.upper().replace("/USDT", "").replace("USDT", "").strip()

    # 原生币直接返回空（无合约地址）
    if symbol in NATIVE_COINS:
        return {}

    # 检查缓存
    if symbol in _contract_cache and time.time() < _cache_expire.get(symbol, 0):
        return _contract_cache[symbol]

    result = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: 用已知 id 或搜索获取 CoinGecko coin id
            coin_id = KNOWN_COINGECKO_IDS.get(symbol)
            if not coin_id:
                coin_id = await _search_coin_id(client, symbol)

            if not coin_id:
                _contract_cache[symbol] = {}
                _cache_expire[symbol] = time.time() + 3600  # 搜不到，缓存1小时
                return {}

            # Step 2: 获取 coin detail，拿 platforms 字段
            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "market_data": "false",
                "community_data": "false",
                "developer_data": "false",
            }
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                platforms: Dict[str, str] = data.get("platforms", {})

                # 按优先顺序整理
                for platform_id in PLATFORM_PRIORITY:
                    addr = platforms.get(platform_id, "").strip()
                    if addr:
                        display = PLATFORM_DISPLAY.get(platform_id, platform_id.upper()[:6])
                        result[display] = addr

                # 还有其他链，也加进去（最多展示8条）
                for platform_id, addr in platforms.items():
                    if platform_id in PLATFORM_PRIORITY or not addr.strip():
                        continue
                    if len(result) >= 8:
                        break
                    display = PLATFORM_DISPLAY.get(platform_id, platform_id.upper()[:6])
                    result[display] = addr.strip()

            elif resp.status_code == 429:
                logger.warning(f"CoinGecko API 限速，稍后重试: {symbol}")
            else:
                logger.debug(f"CoinGecko 查询失败 {symbol}: HTTP {resp.status_code}")

    except Exception as e:
        logger.warning(f"查询合约地址失败 {symbol}: {e}")

    _contract_cache[symbol] = result
    _cache_expire[symbol] = time.time() + CACHE_TTL
    return result


async def _search_coin_id(client: httpx.AsyncClient, symbol: str) -> Optional[str]:
    """通过 CoinGecko search 接口搜索 coin id"""
    try:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": symbol},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        coins = data.get("coins", [])
        # 优先完全匹配 symbol
        for c in coins[:10]:
            if c.get("symbol", "").upper() == symbol:
                return c.get("id")
        # 退而求其次取第一个
        if coins:
            return coins[0].get("id")
    except Exception as e:
        logger.debug(f"CoinGecko search 失败 {symbol}: {e}")
    return None


async def batch_get_contracts(symbols: List[str], concurrency: int = 3) -> Dict[str, Dict[str, str]]:
    """批量查询合约地址，限制并发数避免被限速"""
    sem = asyncio.Semaphore(concurrency)

    async def _fetch(sym):
        async with sem:
            await asyncio.sleep(0.3)  # CoinGecko 免费 API 限速保护
            return sym, await get_contract_addresses(sym)

    tasks = [_fetch(s) for s in symbols]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    out = {}
    for item in results_list:
        if isinstance(item, tuple):
            sym, addrs = item
            out[sym] = addrs
    return out
