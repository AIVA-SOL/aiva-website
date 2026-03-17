"""
╔══════════════════════════════════════════════════════════════════╗
║         AIVA DeFi 套利监控机器人  v3.0                           ║
║         数据源：Jupiter API（精准链上报价）+ DexScreener（备用）  ║
║                 + DeFi Llama（稳定币收益率）                     ║
║         风险等级：⭐⭐☆☆☆  最低风险 — 只监控，不自动动资金      ║
╚══════════════════════════════════════════════════════════════════╝

数据源说明（v3 升级内容）
─────────────────────────────────────────────────────────────────
【主数据源】Jupiter API v2（api.jup.ag）
  - 聚合 Raydium / Orca / Meteora / Phoenix / Lifinity 等 20+ DEX
  - 精准链上报价，误差 < 0.01%（vs DexScreener 约 0.5~1%）
  - 支持任意 SPL Token，包括 $AIVA 等小市值代币
  - 需要 API Key（免费，portal.jup.ag）

【备用数据源】DexScreener（无需 Key）
  - 当 Jupiter API 不可用时自动降级使用
  - 误差较大，仅用于参考

【收益率数据】DeFi Llama
  - 权威 DeFi 数据聚合，覆盖 Kamino / MarginFi / Solend 等
  - 完全免费，无需 Key

策略说明
─────────────────────────────────────────────────────────────────
1. 【Jupiter 精准套利监控】
   用真实链上报价计算双向套利价差
   → USDC → Token → USDC（买入再卖回）
   → 精确计算 DEX 手续费后的净利润
   
2. 【稳定币收益监控】
   通过 DeFi Llama 追踪 Kamino / MarginFi 存款 APY
   
3. 【价格追踪】
   Jupiter Price API → 所有 Solana 代币实时价格
"""

import asyncio
import aiohttp
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

# 从 config 导入（兼容 JUPITER_API_KEY 新字段）
try:
    from config import PROXY, HELIUS_API_KEY, AIVA_CONTRACT, JUPITER_API_KEY
except ImportError:
    from config import PROXY, HELIUS_API_KEY, AIVA_CONTRACT
    JUPITER_API_KEY = ""

logger = logging.getLogger("arb_bot")

# ─────────────────────────── 常量配置 ────────────────────────────

MINT = {
    "USDC":  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "SOL":   "So11111111111111111111111111111111111111112",
    "USDT":  "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "BONK":  "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "JUP":   "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "WIF":   "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "AIVA":  AIVA_CONTRACT,
}

# ── Jupiter API v2 端点（需要 API Key）─────────────────────────
JUP_BASE         = "https://api.jup.ag"
JUP_QUOTE_URL    = f"{JUP_BASE}/swap/v1/quote"              # 精准报价 ✅ Basic Plan
JUP_PRICE_URL    = f"{JUP_BASE}/swap/v1/price"             # 批量价格（Basic Plan 路径）
JUP_TOKENS_URL   = f"{JUP_BASE}/tokens/v1/tagged/verified" # 已验证代币列表

# ── DexScreener（备用，无需Key）────────────────────────────────
DEXSCREENER_URL  = "https://api.dexscreener.com/tokens/v1/solana/{mint}"

# ── DeFi Llama（收益率，无需Key）──────────────────────────────
DEFILLAMA_URL    = "https://yields.llama.fi/pools"

# 套利参数
MIN_SPREAD_PCT   = 0.30    # 最低价差阈值 %
SCAN_INPUT_USDC  = 100.0   # 模拟扫描金额（$100 USDC）- 更贴近实际
USDC_DECIMALS    = 6       # USDC 精度
SOL_DECIMALS     = 9       # SOL 精度


# ─────────────────────── HTTP 工具 ───────────────────────────────

def _jup_headers() -> Dict[str, str]:
    """
    Jupiter API 请求头
    认证方式：x-api-key（不是 Bearer），官方文档确认
    """
    h = {
        "Accept":       "application/json",
        "Content-Type": "application/json",
    }
    if JUPITER_API_KEY:
        h["x-api-key"] = JUPITER_API_KEY   # ← 正确的 Jupiter 认证头
    return h


async def _http_get(url: str, params: dict = None,
                    headers: dict = None, timeout: int = 20) -> Optional[Any]:
    """通用 GET，走 Clash 代理，跳过 SSL 验证"""
    connector = aiohttp.TCPConnector(ssl=False)
    _timeout  = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=_timeout) as s:
            async with s.get(url, params=params, headers=headers, proxy=PROXY) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                else:
                    logger.warning(f"HTTP {resp.status} ← {url[:70]}")
                    return None
    except asyncio.TimeoutError:
        logger.warning(f"Timeout ← {url[:70]}")
        return None
    except Exception as e:
        logger.warning(f"GET error ← {url[:70]}: {e}")
        return None


# ─────────────────── Jupiter Price API v2 ────────────────────────

async def get_jupiter_prices(mints: List[str]) -> Dict[str, float]:
    """
    批量获取代币 USD 价格（Jupiter Price API v2）
    精度远高于 DexScreener，直接来自链上最新成交
    
    返回: {mint_address: usd_price}
    """
    if not mints:
        return {}

    # Jupiter 每次最多查 100 个
    chunk_size = 50
    prices = {}
    hdrs = _jup_headers()

    for i in range(0, len(mints), chunk_size):
        chunk = mints[i:i+chunk_size]
        params = {"ids": ",".join(chunk)}
        data = await _http_get(JUP_PRICE_URL, params=params, headers=hdrs)
        if data and isinstance(data.get("data"), dict):
            for mint, info in data["data"].items():
                try:
                    prices[mint] = float(info.get("price", 0))
                except:
                    pass
        await asyncio.sleep(0.1)

    return prices


async def get_token_prices() -> Dict[str, float]:
    """
    获取主要代币价格
    优先 Jupiter API v2，失败时降级到 DexScreener
    """
    mints  = list(MINT.values())
    prices = {}

    # 方法1：Jupiter API（精准）
    if JUPITER_API_KEY:
        try:
            raw = await get_jupiter_prices(mints)
            # 转成 symbol → price
            for symbol, mint in MINT.items():
                if mint in raw and raw[mint] > 0:
                    prices[symbol] = raw[mint]

            if prices:
                logger.info(f"[Price] Jupiter API ✅ 获取 {len(prices)} 个代币价格")
                return prices
        except Exception as e:
            logger.warning(f"[Price] Jupiter 失败，降级到 DexScreener: {e}")

    # 方法2：DexScreener（备用）
    logger.info("[Price] 使用 DexScreener 备用数据源")
    for symbol, mint in MINT.items():
        url  = DEXSCREENER_URL.format(mint=mint)
        data = await _http_get(url)
        if data and isinstance(data, list):
            for pair in data:
                try:
                    p = float(pair.get("priceUsd", 0) or 0)
                    liq = float((pair.get("liquidity") or {}).get("usd", 0) or 0)
                    if p > 0 and liq > 10000:
                        prices[symbol] = p
                        break
                except:
                    pass
        await asyncio.sleep(0.2)

    return prices


# ─────────────────── Jupiter Quote API（精准套利计算）────────────

@dataclass
class QuoteResult:
    """Jupiter 报价结果"""
    input_mint:    str
    output_mint:   str
    in_amount:     int      # 原始精度
    out_amount:    int      # 原始精度
    price_impact:  float    # 价格冲击 %
    route_plan:    List     # 路由计划（经过哪些DEX）
    slippage_bps:  int      # 滑点 bps


async def get_jupiter_quote(
    input_mint: str,
    output_mint: str,
    amount: int,         # 原始精度（USDC=6位，SOL=9位）
    slippage_bps: int = 50
) -> Optional[QuoteResult]:
    """
    调用 Jupiter Quote API v1 获取精准链上报价
    这是整个套利计算的核心，误差 < 0.01%
    """
    params = {
        "inputMint":   input_mint,
        "outputMint":  output_mint,
        "amount":      str(amount),
        "slippageBps": str(slippage_bps),
        "onlyDirectRoutes": "false",   # 允许多跳路由
    }
    hdrs = _jup_headers()
    data = await _http_get(JUP_QUOTE_URL, params=params, headers=hdrs)

    if not data or "outAmount" not in data:
        return None

    try:
        return QuoteResult(
            input_mint   = input_mint,
            output_mint  = output_mint,
            in_amount    = int(data["inAmount"]),
            out_amount   = int(data["outAmount"]),
            price_impact = float(data.get("priceImpactPct", 0)),
            route_plan   = data.get("routePlan", []),
            slippage_bps = slippage_bps,
        )
    except Exception as e:
        logger.warning(f"[Quote] 解析失败: {e}")
        return None


async def calculate_round_trip_profit(
    token_symbol: str,
    usdc_amount: float = SCAN_INPUT_USDC
) -> Optional[Dict]:
    """
    精确计算双向套利利润
    策略：USDC → Token（买入）→ USDC（卖回）
    
    如果 最终USDC > 初始USDC，说明有套利空间
    这个方法使用真实 Jupiter 链上报价，不是估算
    """
    mint = MINT.get(token_symbol)
    if not mint:
        return None

    usdc_mint    = MINT["USDC"]
    amount_raw   = int(usdc_amount * 10**USDC_DECIMALS)  # USDC 6位精度

    # 第一跳：USDC → Token（买入）
    q1 = await get_jupiter_quote(usdc_mint, mint, amount_raw)
    if not q1 or q1.out_amount <= 0:
        return None

    await asyncio.sleep(0.3)  # 避免限速

    # 第二跳：Token → USDC（卖回）
    q2 = await get_jupiter_quote(mint, usdc_mint, q1.out_amount)
    if not q2 or q2.out_amount <= 0:
        return None

    # 计算净利润
    final_usdc  = q2.out_amount / 10**USDC_DECIMALS
    profit_usdc = final_usdc - usdc_amount
    profit_pct  = profit_usdc / usdc_amount * 100

    # 解析路由（买入经过哪些DEX）
    buy_route   = [step.get("swapInfo", {}).get("ammKey", "?")[:8]
                   for step in q1.route_plan[:3]]
    sell_route  = [step.get("swapInfo", {}).get("ammKey", "?")[:8]
                   for step in q2.route_plan[:3]]

    # 路由 label（更可读的DEX名称）
    buy_dex  = " → ".join(
        step.get("swapInfo", {}).get("label", "?") for step in q1.route_plan[:2]
    ) or "Jupiter"
    sell_dex = " → ".join(
        step.get("swapInfo", {}).get("label", "?") for step in q2.route_plan[:2]
    ) or "Jupiter"

    # 估算手续费（Solana 每笔约 $0.00025，DEX fee 约 0.25%）
    dex_fee     = usdc_amount * 0.003   # 来回两笔约 0.3% DEX fee
    sol_fee     = 0.001                 # 约 $0.001 链上 gas
    net_profit  = profit_usdc - dex_fee - sol_fee

    return {
        "token":         token_symbol,
        "input_usdc":    usdc_amount,
        "output_usdc":   round(final_usdc, 4),
        "gross_profit":  round(profit_usdc, 4),
        "dex_fee":       round(dex_fee, 4),
        "net_profit":    round(net_profit, 4),
        "profit_pct":    round(profit_pct, 4),
        "buy_dex":       buy_dex,
        "sell_dex":      sell_dex,
        "price_impact_buy":  round(q1.price_impact * 100, 4),
        "price_impact_sell": round(q2.price_impact * 100, 4),
        "viable":        net_profit > 0 and profit_pct > MIN_SPREAD_PCT,
        "data_source":   "jupiter_api_v2",
    }


# ─────────────────── DexScreener 备用套利扫描 ────────────────────

@dataclass
class DexPrice:
    dex:       str
    price_usd: float
    liquidity: float
    volume_24h: float = 0.0


async def scan_dexscreener_arbitrage(token_symbol: str) -> Optional[Dict]:
    """DexScreener 备用套利检测（精度较低，误差约 0.5~1%）"""
    mint = MINT.get(token_symbol)
    if not mint:
        return None

    url  = DEXSCREENER_URL.format(mint=mint)
    data = await _http_get(url)
    if not data or not isinstance(data, list):
        return None

    prices = []
    for pair in data[:15]:
        try:
            p   = float(pair.get("priceUsd", 0) or 0)
            liq = float((pair.get("liquidity") or {}).get("usd", 0) or 0)
            if p > 0 and liq >= 10_000:
                prices.append(DexPrice(
                    dex       = pair.get("dexId", "?"),
                    price_usd = p,
                    liquidity = liq,
                    volume_24h= float((pair.get("volume") or {}).get("h24", 0) or 0),
                ))
        except:
            pass

    if len(prices) < 2:
        return None

    prices.sort(key=lambda x: x.liquidity, reverse=True)
    cheapest  = min(prices[:5], key=lambda x: x.price_usd)
    expensive = max(prices[:5], key=lambda x: x.price_usd)

    if cheapest.dex == expensive.dex:
        return None

    spread = (expensive.price_usd - cheapest.price_usd) / cheapest.price_usd * 100
    gross  = SCAN_INPUT_USDC * spread / 100
    fee    = 0.006
    net    = gross - fee

    return {
        "token":        token_symbol,
        "input_usdc":   SCAN_INPUT_USDC,
        "buy_dex":      cheapest.dex,
        "sell_dex":     expensive.dex,
        "buy_price":    cheapest.price_usd,
        "sell_price":   expensive.price_usd,
        "profit_pct":   round(spread, 4),
        "net_profit":   round(net, 4),
        "viable":       spread >= MIN_SPREAD_PCT and net > 0,
        "data_source":  "dexscreener",
    }


# ─────────────────────── 稳定币收益率 ────────────────────────────

async def get_yield_opportunities() -> Dict[str, Any]:
    """
    DeFi Llama 稳定币收益率
    返回 Kamino / MarginFi / Solend 等协议的真实 APY
    """
    data = await _http_get(DEFILLAMA_URL, timeout=30)
    if not data:
        return _yield_fallback()

    pools_raw     = data.get("data", [])
    target_protos = {"kamino", "marginfi", "solend", "drift", "save"}
    target_assets = {"USDC", "USDT", "PYUSD", "USDS"}
    results       = []

    for pool in pools_raw:
        try:
            if pool.get("chain", "").lower() != "solana":
                continue
            symbol  = pool.get("symbol", "").upper()
            project = pool.get("project", "").lower()
            apy     = float(pool.get("apy", 0) or 0)
            tvl     = float(pool.get("tvlUsd", 0) or 0)

            if not any(t in project for t in target_protos):
                continue
            if not any(a in symbol for a in target_assets):
                continue
            if tvl < 1_000_000 or apy <= 0 or apy > 150:
                continue

            results.append({
                "protocol":   pool.get("project", ""),
                "asset":      symbol,
                "apy":        round(apy, 2),
                "tvl_usd":    tvl,
                "risk_score": 2,
                "is_estimate": False,
            })
        except:
            pass

    results.sort(key=lambda x: x["apy"], reverse=True)

    out = {}
    for r in results[:8]:
        key     = f"{r['protocol']}_{r['asset']}"
        out[key] = r

    return out if out else _yield_fallback()


def _yield_fallback() -> Dict[str, Any]:
    """DeFi Llama 不可用时的历史观测值"""
    return {
        "kamino_USDC":   {"protocol": "kamino",   "asset": "USDC",  "apy": 3.5,  "tvl_usd": 800_000_000, "is_estimate": True},
        "kamino_PYUSD":  {"protocol": "kamino",   "asset": "PYUSD", "apy": 7.8,  "tvl_usd": 35_000_000,  "is_estimate": True},
        "marginfi_USDC": {"protocol": "marginfi", "asset": "USDC",  "apy": 3.2,  "tvl_usd": 400_000_000, "is_estimate": True},
        "solend_USDC":   {"protocol": "solend",   "asset": "USDC",  "apy": 2.9,  "tvl_usd": 150_000_000, "is_estimate": True},
    }


# ─────────────────────── 主扫描引擎 ──────────────────────────────

class ArbScanEngine:
    """
    套利扫描引擎 v3
    主数据源：Jupiter API v2（精准链上报价）
    备用数据源：DexScreener
    """

    def __init__(self):
        self.scan_count:   int   = 0
        self.last_scan_ts: float = 0
        self.jupiter_ok:   bool  = bool(JUPITER_API_KEY)

    async def run_full_scan(self) -> Dict[str, Any]:
        """
        完整扫描，返回结构化结果
        v3：优先使用 Jupiter API 精准报价
        """
        start = time.time()
        self.scan_count += 1
        mode  = "Jupiter API v2" if self.jupiter_ok else "DexScreener（备用）"
        logger.info(f"[ArbEngine v3] 第 {self.scan_count} 次扫描 | 数据源: {mode}")

        result: Dict[str, Any] = {
            "scan_id":       self.scan_count,
            "timestamp":     start,
            "data_source":   mode,
            "arb_opps":      [],
            "apy_data":      {},
            "prices":        {},
            "best_strategy": {},
            "elapsed_sec":   0,
        }

        # ── 1. 代币价格（Jupiter Price API）─────────────────────
        try:
            prices = await get_token_prices()
            result["prices"] = {k: round(v, 6) for k, v in prices.items()}
            src = "Jupiter" if self.jupiter_ok else "DexScreener"
            logger.info(f"[Price] {src}: {result['prices']}")
        except Exception as e:
            logger.warning(f"[Price] 获取失败: {e}")

        # ── 2. 套利扫描 ─────────────────────────────────────────
        scan_tokens = ["SOL", "JUP", "BONK", "WIF"]
        arb_opps    = []

        for token in scan_tokens:
            try:
                if self.jupiter_ok:
                    # 方法A：Jupiter 精准双向报价
                    opp = await calculate_round_trip_profit(token, SCAN_INPUT_USDC)
                else:
                    # 方法B：DexScreener 备用
                    opp = await scan_dexscreener_arbitrage(token)

                if opp:
                    icon = "✅" if opp.get("viable") else "❌"
                    logger.info(
                        f"[Arb] {token}: {icon} "
                        f"spread={opp.get('profit_pct',0):+.3f}% "
                        f"net=${opp.get('net_profit',0):+.4f} "
                        f"[{opp.get('data_source','')}]"
                    )
                    arb_opps.append(opp)

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(f"[ArbEngine] {token} 扫描失败: {e}")

        result["arb_opps"] = sorted(
            arb_opps, key=lambda x: x.get("profit_pct", 0), reverse=True
        )

        # ── 3. 稳定币收益率 ──────────────────────────────────────
        try:
            result["apy_data"] = await get_yield_opportunities()
            count = len(result["apy_data"])
            logger.info(f"[APY] 获取 {count} 个收益池")
        except Exception as e:
            logger.warning(f"[APY] 获取失败: {e}")

        # ── 4. 选最优策略 ─────────────────────────────────────
        result["best_strategy"] = self._pick_best(
            result["arb_opps"], result["apy_data"]
        )

        result["elapsed_sec"] = round(time.time() - start, 2)
        self.last_scan_ts     = time.time()

        viable = sum(1 for a in arb_opps if a.get("viable"))
        logger.info(
            f"[ArbEngine] 完成 {result['elapsed_sec']}s | "
            f"有效套利: {viable} | "
            f"最优: {result['best_strategy'].get('name', 'N/A')}"
        )
        return result

    def _pick_best(self, arb_opps: List, apy_data: Dict) -> Dict:
        candidates = []

        for opp in arb_opps:
            if opp.get("viable"):
                candidates.append({
                    "name":          f"套利: {opp['token']} ${opp.get('net_profit',0):.3f}/轮",
                    "type":          "arbitrage",
                    "estimated_apy": opp.get("profit_pct", 0) * 24 * 365,
                    "risk":          "medium",
                    "data_source":   opp.get("data_source", ""),
                })

        for key, y in apy_data.items():
            if y.get("apy", 0) > 0:
                est_flag = " (估算)" if y.get("is_estimate") else ""
                candidates.append({
                    "name":          f"存款: {y['protocol'].title()} {y['asset']} {y['apy']:.1f}%{est_flag}",
                    "type":          "yield",
                    "estimated_apy": y["apy"],
                    "risk":          "low",
                    "data_source":   "defillama",
                })

        if not candidates:
            return {"name": "等待机会", "estimated_apy": 0, "type": "none"}

        low_risk = [c for c in candidates if c["risk"] == "low"]
        if low_risk:
            return max(low_risk, key=lambda x: x["estimated_apy"])
        return max(candidates, key=lambda x: x["estimated_apy"])


# 全局引擎单例
engine = ArbScanEngine()


# ─────────────────────── 独立运行演示 ───────────────────────────

async def _demo():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    has_key = bool(JUPITER_API_KEY)
    src_label = "Jupiter API v2（精准链上报价）" if has_key else "DexScreener（备用）"

    print("\n🤖 AIVA 套利扫描引擎 v3 — 真实数据演示")
    print("=" * 65)
    print(f"数据源: {src_label}")
    if has_key:
        print(f"Jupiter Key: {JUPITER_API_KEY[:8]}...{JUPITER_API_KEY[-4:]}")
    print("=" * 65)

    result = await engine.run_full_scan()

    print(f"\n⏱  扫描耗时: {result['elapsed_sec']}s")
    print(f"📡 数据源:   {result['data_source']}")

    print(f"\n💰 代币实时价格:")
    for token, price in result["prices"].items():
        print(f"   {token:6s}: ${price:,.4f}")

    print(f"\n⚡ 套利机会 ({len(result['arb_opps'])} 个代币):")
    for opp in result["arb_opps"]:
        icon = "✅ 可执行" if opp["viable"] else "❌ 不足"
        src  = opp.get("data_source", "")
        print(f"   {opp['token']}: {icon}  价差={opp.get('profit_pct',0):+.3f}%  净利=${opp.get('net_profit',0):+.4f}  [{src}]")
        if opp.get("buy_dex"):
            print(f"        买: {opp['buy_dex']}  卖: {opp['sell_dex']}")

    print(f"\n📈 稳定币收益率 (Top 5):")
    for i, (key, y) in enumerate(list(result["apy_data"].items())[:5]):
        est = " *估算" if y.get("is_estimate") else ""
        tvl = y.get("tvl_usd", 0)
        tvl_str = f"${tvl/1e6:.0f}M TVL" if tvl >= 1e6 else f"${tvl:,.0f}"
        print(f"   {i+1}. {y['protocol'].title()} {y['asset']}: {y['apy']:.1f}% APY  {tvl_str}{est}")

    print(f"\n🏆 当前最优策略:")
    best = result["best_strategy"]
    print(f"   名称: {best.get('name', 'N/A')}")
    print(f"   类型: {best.get('type','N/A')} | 估算年化: {best.get('estimated_apy',0):.1f}%")
    print(f"\n{'='*65}")
    print("✅ 扫描完成！以上为监控分析，不涉及任何资金操作。")


if __name__ == "__main__":
    asyncio.run(_demo())
