"""
solana_data.py — Solana 链上数据获取模块
封装 Helius API + Birdeye API + Jupiter API
"""

import aiohttp
import asyncio
import time
from typing import Optional
from config import HELIUS_API_KEY, BIRDEYE_API_KEY, AIVA_CONTRACT, PROXY

# ── 代理配置（Clash Verge HTTP 代理）──────────────────────────────
# Helius RPC/API 不走代理（国内可直连）
# 其余境外接口全部走代理
# 不需要代理的域名前缀（直连更快）
_NO_PROXY_HOSTS = ("helius-rpc.com", "helius.xyz")


HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_API = f"https://api.helius.xyz/v0"
BIRDEYE_BASE = "https://public-api.birdeye.so"

# Jupiter 价格 API v3（免费，无需 key）
JUPITER_PRICE_V3 = "https://api.jup.ag/price/v2"

# Pump.fun 程序 ID
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# DexScreener API（免费）- 新版端点
DEXSCREENER_BASE = "https://api.dexscreener.com/latest"
DEXSCREENER_V1 = "https://api.dexscreener.com"


# ─────────────────────── 通用请求 ────────────────────────────────

def _need_proxy(url: str) -> str:
    """判断该 URL 是否需要走代理，返回代理地址或 None"""
    for host in _NO_PROXY_HOSTS:
        if host in url:
            return None
    return PROXY


async def _get(url: str, params: dict = None, headers: dict = None) -> Optional[dict]:
    """通用 GET 请求，境外接口自动走代理，失败返回 None"""
    proxy = _need_proxy(url)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, headers=headers,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                print(f"[HTTP GET {resp.status}] {url}")
    except Exception as e:
        print(f"[HTTP GET 错误] {url}: {e}")
    return None


async def _post(url: str, json_data: dict = None, headers: dict = None) -> Optional[dict]:
    """通用 POST 请求，境外接口自动走代理"""
    proxy = _need_proxy(url)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=json_data, headers=headers,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                print(f"[HTTP POST {resp.status}] {url}")
    except Exception as e:
        print(f"[HTTP POST 错误] {url}: {e}")
    return None


# ─────────────────────── Solana 价格 ─────────────────────────────

async def get_sol_price() -> float:
    """获取 SOL/USD 当前价格，多数据源备用"""
    # 方式1：DexScreener 搜索 SOL/USDC 主流交易对
    SOL_USDC_PAIR = "8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj"  # Raydium SOL/USDC
    data = await _get(f"{DEXSCREENER_V1}/token-pairs/v1/solana/So11111111111111111111111111111111111111112")
    if data and isinstance(data, list):
        for p in data:
            price_str = p.get("priceUsd", "")
            if price_str:
                try:
                    price = float(price_str)
                    if price > 1:   # SOL 价格一定 > $1
                        return price
                except (ValueError, TypeError):
                    pass

    # 方式2：DexScreener 查具体的 SOL/USDC 交易对
    data2 = await _get(f"{DEXSCREENER_V1}/latest/dex/pairs/solana/{SOL_USDC_PAIR}")
    if data2 and data2.get("pair"):
        try:
            return float(data2["pair"].get("priceUsd", 0))
        except (ValueError, TypeError):
            pass

    # 方式3：Binance 公开接口（无需代理）
    data3 = await _get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "SOLUSDT"})
    if data3 and "price" in data3:
        try:
            return float(data3["price"])
        except (ValueError, TypeError):
            pass

    return 0.0


async def get_token_price(mint: str) -> Optional[dict]:
    """
    获取代币价格信息（DexScreener，免费无需 key）
    返回: {price_usd, price_change_24h, volume_24h, market_cap, liquidity, symbol, name}
    """
    data = await _get(f"{DEXSCREENER_V1}/token-pairs/v1/solana/{mint}")
    if data and isinstance(data, list) and len(data) > 0:
        pair = data[0]
        return {
            "price_usd":        float(pair.get("priceUsd", 0) or 0),
            "price_change_24h": pair.get("priceChange", {}).get("h24", 0),
            "volume_24h":       pair.get("volume", {}).get("h24", 0),
            "market_cap":       pair.get("fdv", 0),
            "liquidity":        pair.get("liquidity", {}).get("usd", 0),
            "symbol":           pair.get("baseToken", {}).get("symbol", ""),
            "name":             pair.get("baseToken", {}).get("name", ""),
        }
    # 备用：search 端点
    data2 = await _get(f"{DEXSCREENER_BASE}/dex/search", params={"q": mint})
    if data2 and data2.get("pairs"):
        pair = data2["pairs"][0]
        return {
            "price_usd":        float(pair.get("priceUsd", 0) or 0),
            "price_change_24h": pair.get("priceChange", {}).get("h24", 0),
            "volume_24h":       pair.get("volume", {}).get("h24", 0),
            "market_cap":       pair.get("fdv", 0),
            "liquidity":        pair.get("liquidity", {}).get("usd", 0),
            "symbol":           pair.get("baseToken", {}).get("symbol", ""),
            "name":             pair.get("baseToken", {}).get("name", ""),
        }
    return None


async def get_aiva_price() -> Optional[dict]:
    """获取 AIVA 完整代币数据（DexScreener + Helius RPC）"""
    result = {}

    # ── DexScreener：价格、市值、买卖数据 ──
    data = await _get(f"{DEXSCREENER_V1}/token-pairs/v1/solana/{AIVA_CONTRACT}")
    if data and isinstance(data, list) and len(data) > 0:
        pair = data[0]
        txns_h24 = pair.get("txns", {}).get("h24", {})
        txns_h1  = pair.get("txns", {}).get("h1", {})
        result.update({
            "price_usd":        float(pair.get("priceUsd", 0) or 0),
            "price_native":     float(pair.get("priceNative", 0) or 0),
            "price_change_1h":  pair.get("priceChange", {}).get("h1", 0),
            "price_change_6h":  pair.get("priceChange", {}).get("h6", 0),
            "price_change_24h": pair.get("priceChange", {}).get("h24", 0),
            "volume_24h":       pair.get("volume", {}).get("h24", 0),
            "volume_1h":        pair.get("volume", {}).get("h1", 0),
            "liquidity":        pair.get("liquidity", {}).get("usd", 0),
            "market_cap":       pair.get("fdv", 0) or pair.get("marketCap", 0),
            "dex":              pair.get("dexId", ""),
            "pair_addr":        pair.get("pairAddress", ""),
            "buys_24h":         txns_h24.get("buys", 0),
            "sells_24h":        txns_h24.get("sells", 0),
            "buys_1h":          txns_h1.get("buys", 0),
            "sells_1h":         txns_h1.get("sells", 0),
            "pair_age_ts":      pair.get("pairCreatedAt", 0),
        })
    else:
        # 备用：search 端点
        data2 = await _get(f"{DEXSCREENER_BASE}/dex/search", params={"q": AIVA_CONTRACT})
        if data2 and data2.get("pairs"):
            pair = data2["pairs"][0]
            result.update({
                "price_usd":        float(pair.get("priceUsd", 0) or 0),
                "price_change_24h": pair.get("priceChange", {}).get("h24", 0),
                "volume_24h":       pair.get("volume", {}).get("h24", 0),
                "liquidity":        pair.get("liquidity", {}).get("usd", 0),
                "market_cap":       pair.get("fdv", 0),
                "dex":              pair.get("dexId", ""),
                "pair_addr":        pair.get("pairAddress", ""),
            })

    # ── Helius RPC：总供应量 + Top 持有者 ──
    supply_resp = await _post(HELIUS_RPC, json_data={
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenSupply",
        "params": [AIVA_CONTRACT]
    })
    if supply_resp and "result" in supply_resp:
        val = supply_resp["result"]["value"]
        result["total_supply"] = float(val.get("uiAmount", 0))
        result["decimals"]     = val.get("decimals", 6)

    holders_resp = await _post(HELIUS_RPC, json_data={
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenLargestAccounts",
        "params": [AIVA_CONTRACT, {"commitment": "finalized"}]
    })
    if holders_resp and "result" in holders_resp:
        accounts = holders_resp["result"]["value"]
        result["top_holder_pct"] = 0
        if accounts and result.get("total_supply", 0) > 0:
            top1_amt = float(accounts[0].get("uiAmount", 0))
            result["top_holder_pct"] = round(top1_amt / result["total_supply"] * 100, 1)
        result["top_holders_count"] = len(accounts)

    return result if result else None


# ─────────────────────── 网络状态 ────────────────────────────────

async def get_network_status() -> dict:
    """获取 Solana 网络状态（TPS + 平均 Gas）"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getRecentPerformanceSamples", "params": [5]}
    data = await _post(HELIUS_RPC, json_data=payload)
    tps = 0
    if data and "result" in data:
        samples = data["result"]
        if samples:
            total_tx = sum(s.get("numTransactions", 0) for s in samples)
            total_sec = sum(s.get("samplePeriodSecs", 1) for s in samples)
            tps = round(total_tx / total_sec, 1) if total_sec else 0

    # 获取优先费用
    fee_payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getPriorityFeeEstimate",
        "params": [{"options": {"priorityLevel": "Medium"}}]
    }
    fee_data = await _post(HELIUS_RPC, json_data=fee_payload)
    priority_fee = 0
    if fee_data and "result" in fee_data:
        priority_fee = fee_data["result"].get("priorityFeeEstimate", 0)

    # 获取 Epoch 信息
    epoch_payload = {"jsonrpc": "2.0", "id": 1, "method": "getEpochInfo", "params": []}
    epoch_data = await _post(HELIUS_RPC, json_data=epoch_payload)
    epoch_info = {}
    if epoch_data and "result" in epoch_data:
        r = epoch_data["result"]
        epoch_info = {
            "epoch": r.get("epoch"),
            "slot":  r.get("absoluteSlot"),
        }

    return {
        "tps":          tps,
        "priority_fee": priority_fee,
        "epoch":        epoch_info.get("epoch", "N/A"),
        "slot":         epoch_info.get("slot", "N/A"),
    }


# ─────────────────────── 大额交易监控 ────────────────────────────

async def get_recent_large_transactions(min_usd: float = 10000, limit: int = 20) -> list:
    """
    获取最近的大额 SOL 交易（Helius Enhanced Transactions API）
    监控 Raydium AMM 程序，捕捉大额 Swap/Transfer
    """
    sol_price = await get_sol_price()
    if sol_price <= 0:
        sol_price = 150.0  # 兜底价格，避免因价格获取失败导致功能完全失效

    # 监控 Raydium AMM v4（最活跃的 DEX，大额交易多）
    RAYDIUM_AMM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getSignaturesForAddress",
        "params": [RAYDIUM_AMM, {"limit": limit, "commitment": "finalized"}]
    }
    sigs_data = await _post(HELIUS_RPC, json_data=payload)
    if not sigs_data or "result" not in sigs_data:
        return []

    signatures = [s["signature"] for s in sigs_data["result"]]
    if not signatures:
        return []

    # 用 Helius Enhanced API 解析交易
    enhanced = await _post(
        f"{HELIUS_API}/transactions?api-key={HELIUS_API_KEY}",
        json_data={"transactions": signatures[:10]},
    )

    results = []
    if not enhanced:
        return []

    for tx in enhanced:
        native_transfers = tx.get("nativeTransfers", [])
        for t in native_transfers:
            lamports = t.get("amount", 0)
            sol_amount = lamports / 1e9
            usd_val = sol_amount * sol_price
            if usd_val >= min_usd:
                results.append({
                    "signature":   tx.get("signature", ""),
                    "type":        tx.get("type", "SWAP"),
                    "from":        t.get("fromUserAccount", "")[:8] + "...",
                    "to":          t.get("toUserAccount", "")[:8] + "...",
                    "sol_amount":  round(sol_amount, 2),
                    "usd_value":   round(usd_val, 0),
                    "timestamp":   tx.get("timestamp", int(time.time())),
                    "fee":         tx.get("fee", 0),
                })

    # 按金额排序，最大的在前
    results.sort(key=lambda x: x["usd_value"], reverse=True)
    return results


# ─────────────────────── 新币预警 ────────────────────────────────

async def get_new_pump_tokens(limit: int = 20) -> list:
    """
    获取 Pump.fun 最近新发行的代币
    使用 DexScreener token-profiles/latest 端点（新版 API）
    """
    # 方式1：最新 token profiles
    data = await _get(f"{DEXSCREENER_V1}/token-profiles/latest/v1")
    results = []
    if data and isinstance(data, list):
        now = int(time.time())
        for item in data[:limit]:
            # 只要 Solana 链
            if item.get("chainId") != "solana":
                continue
            token_addr = item.get("tokenAddress", "")
            # 进一步获取价格信息
            pair_data = await _get(f"{DEXSCREENER_V1}/token-pairs/v1/solana/{token_addr}")
            price_usd = 0
            liquidity = 0
            volume_5m = 0
            age_min = 9999
            pair_addr = ""
            if pair_data and isinstance(pair_data, list) and len(pair_data) > 0:
                p = pair_data[0]
                price_usd  = float(p.get("priceUsd", 0) or 0)
                liquidity  = p.get("liquidity", {}).get("usd", 0)
                volume_5m  = p.get("volume", {}).get("m5", 0)
                pair_addr  = p.get("pairAddress", "")
                created_at = p.get("pairCreatedAt", 0)
                if created_at:
                    age_min = (now - created_at / 1000) / 60

            results.append({
                "name":      item.get("description", token_addr[:8])[:20],
                "symbol":    "",
                "mint":      token_addr,
                "price_usd": price_usd,
                "liquidity": liquidity,
                "volume_5m": volume_5m,
                "age_min":   round(age_min, 1),
                "pair_addr": pair_addr,
                "dex_url":   f"https://dexscreener.com/solana/{token_addr}",
            })
            if len(results) >= 5:  # 限制请求数量
                break
        return results

    # 方式2：备用 search
    data2 = await _get(f"{DEXSCREENER_BASE}/dex/search", params={"q": "pump solana"})
    if not data2 or "pairs" not in data2:
        return []

    now = int(time.time())
    for pair in data2["pairs"][:limit]:
        if pair.get("chainId") != "solana":
            continue
        created_at = pair.get("pairCreatedAt", 0)
        age_min = ((now - created_at / 1000) / 60) if created_at else 9999
        liquidity = pair.get("liquidity", {}).get("usd", 0)
        results.append({
            "name":      pair.get("baseToken", {}).get("name", "Unknown"),
            "symbol":    pair.get("baseToken", {}).get("symbol", ""),
            "mint":      pair.get("baseToken", {}).get("address", ""),
            "price_usd": float(pair.get("priceUsd", 0) or 0),
            "liquidity": liquidity,
            "volume_5m": pair.get("volume", {}).get("m5", 0),
            "age_min":   round(age_min, 1),
            "pair_addr": pair.get("pairAddress", ""),
            "dex_url":   f"https://dexscreener.com/solana/{pair.get('pairAddress','')}",
        })
    return results


async def get_truly_new_tokens(min_liquidity: float = 500, max_age_min: float = 60) -> list:
    """
    筛选真正新的代币（流动性 >= min_liquidity，上线时间 <= max_age_min 分钟）
    """
    all_tokens = await get_new_pump_tokens(limit=50)
    return [t for t in all_tokens if t["liquidity"] >= min_liquidity and t["age_min"] <= max_age_min]


# ─────────────────────── 趋势榜 ──────────────────────────────────

async def get_trending_tokens(top_n: int = 10) -> list:
    """
    获取 Solana 热门代币趋势榜（Birdeye）
    """
    headers = {"X-API-KEY": BIRDEYE_API_KEY, "x-chain": "solana"}
    data = await _get(
        f"{BIRDEYE_BASE}/defi/token_trending",
        params={"sort_by": "rank", "sort_type": "asc", "offset": 0, "limit": top_n},
        headers=headers
    )
    results = []
    if data and data.get("success"):
        items = data.get("data", {}).get("items", [])
        for i, item in enumerate(items):
            results.append({
                "rank":         i + 1,
                "name":         item.get("name", "Unknown"),
                "symbol":       item.get("symbol", ""),
                "address":      item.get("address", ""),
                "price":        item.get("price", 0),
                "price_change": item.get("price24hChangePercent", 0),
                "volume_24h":   item.get("v24hUSD", 0),
                "liquidity":    item.get("liquidity", 0),
            })
    return results


async def get_trending_dexscreener(top_n: int = 10) -> list:
    """
    DexScreener 趋势榜（免费，无需 key）
    使用 token-boosts/top/v1 端点获取热门代币
    """
    results = []

    # 方式1：Top Boosted Tokens（最活跃助推）
    data = await _get(f"{DEXSCREENER_V1}/token-boosts/top/v1")
    if data and isinstance(data, list):
        solana_items = [d for d in data if d.get("chainId") == "solana"][:top_n]
        for i, item in enumerate(solana_items):
            token_addr = item.get("tokenAddress", "")
            # 获取价格数据
            pair_data = await _get(f"{DEXSCREENER_V1}/token-pairs/v1/solana/{token_addr}")
            symbol = ""
            name = item.get("description", "")[:15]
            price = 0
            change = 0
            volume = 0
            if pair_data and isinstance(pair_data, list) and len(pair_data) > 0:
                p = pair_data[0]
                symbol = p.get("baseToken", {}).get("symbol", "")
                name   = p.get("baseToken", {}).get("name", name)[:15]
                price  = float(p.get("priceUsd", 0) or 0)
                change = p.get("priceChange", {}).get("h24", 0)
                volume = p.get("volume", {}).get("h24", 0)
            results.append({
                "rank":         i + 1,
                "name":         name,
                "symbol":       symbol,
                "address":      token_addr,
                "price":        price,
                "price_change": change,
                "volume_24h":   volume,
                "dex_url":      f"https://dexscreener.com/solana/{token_addr}",
            })
            if len(results) >= 5:  # 控制请求数
                break
        if results:
            return results

    # 方式2：备用 latest boosts
    data2 = await _get(f"{DEXSCREENER_V1}/token-boosts/latest/v1")
    if data2 and isinstance(data2, list):
        solana_items = [d for d in data2 if d.get("chainId") == "solana"][:top_n]
        for i, item in enumerate(solana_items):
            results.append({
                "rank":         i + 1,
                "name":         item.get("description", "")[:15],
                "symbol":       "",
                "address":      item.get("tokenAddress", ""),
                "price":        0,
                "price_change": 0,
                "volume_24h":   0,
                "dex_url":      f"https://dexscreener.com/solana/{item.get('tokenAddress','')}",
            })
    return results


# ─────────────────────── 钱包查询 ────────────────────────────────

async def get_wallet_portfolio(wallet_addr: str) -> Optional[dict]:
    """
    获取钱包资产概览（Helius）
    """
    # SOL 余额
    balance_payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [wallet_addr]
    }
    bal_data = await _post(HELIUS_RPC, json_data=balance_payload)
    sol_balance = 0
    if bal_data and "result" in bal_data:
        sol_balance = bal_data["result"].get("value", 0) / 1e9

    # 代币列表（DAS API）
    assets_payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getAssetsByOwner",
        "params": {
            "ownerAddress": wallet_addr,
            "page": 1, "limit": 50,
            "displayOptions": {"showFungible": True, "showNativeBalance": True}
        }
    }
    assets_data = await _post(HELIUS_RPC, json_data=assets_payload)
    tokens = []
    if assets_data and "result" in assets_data:
        items = assets_data["result"].get("items", [])
        for item in items:
            if item.get("interface") == "FungibleToken":
                token_info = item.get("token_info", {})
                symbol = item.get("content", {}).get("metadata", {}).get("symbol", "")
                tokens.append({
                    "symbol":      symbol or token_info.get("symbol", "Unknown"),
                    "mint":        item.get("id", ""),
                    "balance":     token_info.get("balance", 0),
                    "decimals":    token_info.get("decimals", 0),
                    "price_info":  token_info.get("price_info", {}),
                })

    sol_price = await get_sol_price()
    return {
        "wallet":      wallet_addr,
        "sol_balance": round(sol_balance, 4),
        "sol_usd":     round(sol_balance * sol_price, 2),
        "sol_price":   sol_price,
        "tokens":      tokens[:20],  # 最多显示 20 个代币
        "token_count": len(tokens),
    }


async def check_aiva_holding(wallet_addr: str, min_amount: float = 100000) -> bool:
    """
    检查钱包是否持有足够数量的 AIVA（用于免费验证）
    min_amount: 最少持有数量
    """
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_addr,
            {"mint": AIVA_CONTRACT},
            {"encoding": "jsonParsed"}
        ]
    }
    data = await _post(HELIUS_RPC, json_data=payload)
    if data and "result" in data:
        accounts = data["result"].get("value", [])
        for acc in accounts:
            parsed = acc.get("account", {}).get("data", {}).get("parsed", {})
            info = parsed.get("info", {})
            token_amount = info.get("tokenAmount", {})
            amount = float(token_amount.get("uiAmount", 0) or 0)
            if amount >= min_amount:
                return True
    return False


# ─────────────────────── 格式化工具 ──────────────────────────────

def fmt_num(n: float, decimals: int = 2) -> str:
    """格式化大数字：1234567 -> 1.23M"""
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.{decimals}f}B"
    elif n >= 1_000_000:
        return f"{n/1_000_000:.{decimals}f}M"
    elif n >= 1_000:
        return f"{n/1_000:.{decimals}f}K"
    else:
        return f"{n:.{decimals}f}"


def fmt_price(p: float) -> str:
    """格式化价格，自动选择小数位"""
    if p == 0:
        return "$0"
    if p >= 1:
        return f"${p:.4f}"
    elif p >= 0.001:
        return f"${p:.6f}"
    else:
        return f"${p:.10f}".rstrip('0')


def fmt_change(c: float) -> str:
    """格式化涨跌幅"""
    icon = "📈" if c >= 0 else "📉"
    sign = "+" if c >= 0 else ""
    return f"{icon} {sign}{c:.2f}%"


def shorten_addr(addr: str, n: int = 6) -> str:
    """缩短地址显示"""
    if len(addr) > n * 2:
        return f"{addr[:n]}...{addr[-n:]}"
    return addr
