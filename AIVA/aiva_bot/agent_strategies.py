"""
agent_strategies.py — AIVA DeFi Agent 策略模块
负责：
  1. 稳定币收益监控（Kamino / Solend / MarginFi APY 实时查询）
  2. DEX 套利机会扫描（Jupiter 跨池价差监控）
  3. 策略决策引擎（选择当前最优收益）
  4. 模拟执行（安全模式，记录收益但不真实转账）

架构原则：
  - 第一阶段：全部使用"模拟执行"，所有操作记录 DB，不动链上资金
  - 第二阶段：资金≥$50 USDC 且持续盈利 7 天后，开放真实执行
  - 每次策略执行都写日志，供 /agent_status 展示
"""

import asyncio
import logging
import time
import aiohttp
from typing import Optional
from config import HELIUS_API_KEY, PROXY, AIVA_CONTRACT

logger = logging.getLogger("AIVA_STRATEGY")

PROXY_URL = PROXY
HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# ── 稳定币 MINT ──────────────────────────────────────────────────
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

# ── Jupiter V6 API ────────────────────────────────────────────────
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
JUPITER_PRICE_API = "https://api.jup.ag/price/v2"

# ── Kamino Finance API ────────────────────────────────────────────
KAMINO_API = "https://api.kamino.finance"

# ── MarginFi API ─────────────────────────────────────────────────
MARGINFI_API = "https://storage.googleapis.com/mrgn-public/mrgn-bank-metadata-cache.json"

# ── Solend API ────────────────────────────────────────────────────
SOLEND_API = "https://api.solend.fi/v1"


async def _get(url: str, params: dict = None, headers: dict = None,
               use_proxy: bool = True) -> Optional[dict]:
    """通用 GET（境外接口走代理）"""
    proxy = PROXY_URL if use_proxy else None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, headers=headers,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    ct = resp.headers.get("Content-Type", "")
                    if "json" in ct:
                        return await resp.json()
                    text = await resp.text()
                    import json
                    return json.loads(text)
                logger.warning(f"[GET {resp.status}] {url}")
    except Exception as e:
        logger.error(f"[GET 错误] {url[:60]}: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════
#  模块 1：稳定币收益率查询
# ═══════════════════════════════════════════════════════════════════

async def get_kamino_usdc_apy() -> Optional[float]:
    """
    获取 Kamino Finance USDC 借贷收益 APY（%）
    Kamino 是 Solana 上最大的借贷协议之一
    """
    try:
        # 获取所有市场
        data = await _get(f"{KAMINO_API}/markets/overview-stats")
        if not data:
            return None

        # 查找 USDC 主市场
        markets = data if isinstance(data, list) else data.get("data", [])
        for m in markets:
            name = (m.get("name") or m.get("symbol") or "").upper()
            if "USDC" in name or "USD" in name:
                supply_apy = m.get("supplyAPY") or m.get("lendAPY") or m.get("apy")
                if supply_apy:
                    return float(supply_apy) * 100  # 转为百分比
    except Exception as e:
        logger.error(f"[Kamino APY] {e}")
    return None


async def get_marginfi_usdc_apy() -> Optional[float]:
    """
    获取 MarginFi USDC 借贷存款 APY
    MarginFi 是 Solana 上的主流借贷协议
    """
    try:
        data = await _get(MARGINFI_API, use_proxy=True)
        if data and isinstance(data, list):
            for bank in data:
                mint = bank.get("tokenAddress", "")
                if mint == USDC_MINT or "USDC" in bank.get("tokenSymbol", "").upper():
                    # lendingRate 通常是小数形式
                    rate = bank.get("lendingRate") or bank.get("depositRate")
                    if rate:
                        return float(rate) * 100
    except Exception as e:
        logger.error(f"[MarginFi APY] {e}")
    return None


async def get_all_stable_apys() -> dict:
    """
    并发获取所有稳定币收益率，返回汇总
    """
    results = {}

    # 并发请求多个协议
    kamino_apy, marginfi_apy = await asyncio.gather(
        get_kamino_usdc_apy(),
        get_marginfi_usdc_apy(),
        return_exceptions=True
    )

    # Kamino
    if isinstance(kamino_apy, float) and kamino_apy > 0:
        results["Kamino"] = {"apy": round(kamino_apy, 2), "asset": "USDC", "risk": "Low"}
    else:
        # Fallback：已知 Kamino USDC 历史 APY 约 4-8%，用保守估计
        results["Kamino"] = {"apy": 5.5, "asset": "USDC", "risk": "Low", "is_estimate": True}

    # MarginFi
    if isinstance(marginfi_apy, float) and marginfi_apy > 0:
        results["MarginFi"] = {"apy": round(marginfi_apy, 2), "asset": "USDC", "risk": "Low"}
    else:
        results["MarginFi"] = {"apy": 4.8, "asset": "USDC", "risk": "Low", "is_estimate": True}

    # Solend（用 DexScreener 简单估算，实际需调用 Solend API）
    results["Solend"] = {"apy": 3.9, "asset": "USDC", "risk": "Low", "is_estimate": True}

    # 找出最优
    best_name = max(results, key=lambda k: results[k]["apy"])
    results["_best"] = {"name": best_name, **results[best_name]}

    return results


# ═══════════════════════════════════════════════════════════════════
#  模块 2：Jupiter 套利机会扫描
# ═══════════════════════════════════════════════════════════════════

# 监控的主流代币对（寻找跨池价差）
MONITORED_PAIRS = [
    # (input_mint, output_mint, 描述, 测试金额_USDC)
    (USDC_MINT, "So11111111111111111111111111111111111111112", "USDC→SOL", 10),   # SOL
    (USDC_MINT, "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "USDC→JUP", 10),  # JUP
    (USDC_MINT, "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", "USDC→RAY", 10), # RAY
    ("So11111111111111111111111111111111111111112", USDC_MINT, "SOL→USDC", 1),    # 反向套利
]


async def get_jupiter_quote(
    input_mint: str,
    output_mint: str,
    amount_lamports: int,  # in smallest unit (lamports for SOL, 1e6 for USDC)
) -> Optional[dict]:
    """
    获取 Jupiter V6 最优报价
    返回: {"outAmount": int, "priceImpactPct": float, "routePlan": list}
    """
    params = {
        "inputMint":         input_mint,
        "outputMint":        output_mint,
        "amount":            str(amount_lamports),
        "slippageBps":       "50",  # 0.5% 滑点
        "onlyDirectRoutes":  "false",
    }
    data = await _get(JUPITER_QUOTE_API, params=params, use_proxy=True)
    return data


async def scan_arbitrage_opportunities() -> list:
    """
    扫描当前 Jupiter 上的套利机会。
    策略：检测 A→B→A 的价格差，超过 0.3% 且扣手续费后仍有利润则标记为机会。
    返回套利机会列表
    """
    opportunities = []

    # 获取当前 SOL 价格用于换算
    try:
        from solana_data import get_sol_price
        sol_price = await get_sol_price()
        if sol_price <= 0:
            sol_price = 150.0
    except:
        sol_price = 150.0

    # USDC 测试金额：$10 = 10_000_000 lamports(USDC 6位小数)
    test_usdc_amount = 10_000_000  # $10 USDC

    # 扫描 USDC → Token → USDC 往返套利
    arb_tokens = [
        ("So11111111111111111111111111111111111111112", "SOL",  int(sol_price * 1e9 * 0.1)),  # 测试 0.1 SOL
        ("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "JUP", 100_000_000),  # JUP
        ("4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", "RAY", 10_000_000),  # RAY
    ]

    for token_mint, token_symbol, token_test_amt in arb_tokens:
        try:
            # 第一步：USDC → Token
            quote_in = await get_jupiter_quote(USDC_MINT, token_mint, test_usdc_amount)
            if not quote_in:
                continue
            token_out = int(quote_in.get("outAmount", 0))
            if token_out <= 0:
                continue

            # 第二步：Token → USDC（用刚才得到的输出量作为输入）
            quote_out = await get_jupiter_quote(token_mint, USDC_MINT, token_out)
            if not quote_out:
                continue
            usdc_back = int(quote_out.get("outAmount", 0))
            if usdc_back <= 0:
                continue

            # 计算利润
            profit_usdc_micro = usdc_back - test_usdc_amount
            profit_pct = profit_usdc_micro / test_usdc_amount * 100

            # Solana 手续费估算：约 0.000005 SOL * 2 笔 = ~$0.0015
            fee_usd = 0.003
            profit_usd = (profit_usdc_micro / 1_000_000) - fee_usd

            if profit_pct > 0.3 and profit_usd > 0:
                opportunities.append({
                    "path":          f"USDC → {token_symbol} → USDC",
                    "token":         token_symbol,
                    "token_mint":    token_mint,
                    "input_usdc":    test_usdc_amount / 1_000_000,
                    "output_usdc":   usdc_back / 1_000_000,
                    "profit_pct":    round(profit_pct, 3),
                    "profit_usd":    round(profit_usd, 4),
                    "price_impact":  float(quote_in.get("priceImpactPct", 0)),
                    "timestamp":     int(time.time()),
                    "viable":        profit_usd > 0.01,  # 最低净利 $0.01
                })

            # 不要太频繁，稍微延迟
            await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"[Arb Scan] {token_symbol}: {e}")

    # 按利润排序
    opportunities.sort(key=lambda x: x["profit_pct"], reverse=True)
    return opportunities


# ═══════════════════════════════════════════════════════════════════
#  模块 3：价格监控（新币跟踪）
# ═══════════════════════════════════════════════════════════════════

async def get_jupiter_price(mint: str) -> Optional[float]:
    """通过 Jupiter Price API 获取代币 USD 价格"""
    data = await _get(JUPITER_PRICE_API, params={"ids": mint, "showExtraInfo": "false"})
    if data and "data" in data:
        token_data = data["data"].get(mint, {})
        price = token_data.get("price")
        if price:
            return float(price)
    return None


# ═══════════════════════════════════════════════════════════════════
#  模块 4：策略决策引擎
# ═══════════════════════════════════════════════════════════════════

class StrategyEngine:
    """
    策略决策引擎。
    负责：
      - 定期扫描收益机会
      - 在"模拟模式"下记录假设盈利
      - 达到阈值后通知管理员执行真实操作
    """

    def __init__(self, simulation_mode: bool = True):
        """
        simulation_mode=True：不执行真实链上交易，只记录和统计
        simulation_mode=False：真实执行（需要资金和私钥）
        """
        self.simulation_mode = simulation_mode
        self.scan_count      = 0
        self.last_scan_time  = 0
        self.last_arb_result = []
        self.last_apy_result = {}

    async def run_full_scan(self) -> dict:
        """
        执行一次完整扫描，返回当前市场机会摘要
        内部使用 arb_bot.ArbScanEngine 执行真实的 Jupiter API 扫描
        """
        self.scan_count += 1
        self.last_scan_time = int(time.time())

        logger.info(f"[Strategy] 开始第 {self.scan_count} 次扫描...")

        # 使用 arb_bot 的完整扫描引擎
        try:
            import arb_bot
            raw = await arb_bot.engine.run_full_scan()
            arb_result = raw.get("arb_opps", [])
            apy_result = raw.get("apy_data", {})
        except Exception as e:
            logger.error(f"[Strategy] arb_bot 扫描异常: {e}")
            # 降级到旧方式
            apy_result, arb_result = await asyncio.gather(
                get_all_stable_apys(),
                scan_arbitrage_opportunities(),
                return_exceptions=True
            )
            if isinstance(apy_result, Exception):
                apy_result = {}
            if isinstance(arb_result, Exception):
                arb_result = []

        self.last_apy_result = apy_result
        self.last_arb_result = arb_result

        # 找最优策略
        best_strategy = self._decide_strategy(apy_result, arb_result)

        result = {
            "scan_id":       self.scan_count,
            "timestamp":     self.last_scan_time,
            "apy_data":      apy_result,
            "arb_opps":      arb_result,
            "best_strategy": best_strategy,
            "sim_mode":      self.simulation_mode,
        }

        # 记录到数据库
        import agent_database as adb
        adb.record_strategy_scan(result)

        logger.info(f"[Strategy] 扫描完成，最优策略: {best_strategy.get('name')} "
                    f"预期年化: {best_strategy.get('estimated_apy', 0):.1f}%")

        return result

    def _decide_strategy(self, apy_data: dict, arb_opps: list) -> dict:
        """
        根据当前市场数据，选择最优执行策略
        优先级：套利（即时利润） > 稳定币收益（稳定）
        """
        # 检查是否有高质量套利机会
        viable_arbs = [a for a in arb_opps if a.get("viable") and a["profit_pct"] > 0.5]
        if viable_arbs:
            best_arb = viable_arbs[0]
            return {
                "name":          f"Arbitrage: {best_arb['path']}",
                "type":          "arbitrage",
                "estimated_apy": best_arb["profit_pct"] * 365 * 3,  # 粗略年化
                "details":       best_arb,
                "action":        "execute_arbitrage",
            }

        # 否则选最优稳定币收益
        best_apy = apy_data.get("_best", {})
        if best_apy.get("apy", 0) > 0:
            return {
                "name":          f"Yield: {best_apy.get('name')} {best_apy.get('asset')} {best_apy.get('apy'):.1f}% APY",
                "type":          "yield_farming",
                "estimated_apy": best_apy.get("apy", 0),
                "details":       best_apy,
                "action":        "deposit_yield",
            }

        return {
            "name":          "Hold USDC (No opportunity)",
            "type":          "hold",
            "estimated_apy": 0,
            "details":       {},
            "action":        "none",
        }


# 全局策略引擎实例（模拟模式启动）
engine = StrategyEngine(simulation_mode=True)
