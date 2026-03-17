"""测试 Jupiter API x-api-key 认证方式"""
import httpx
import time

API_KEY = "69175f3b-d09d-4005-8b3a-4a9b27a09cf8"
HEADERS = {
    "x-api-key":    API_KEY,      # ← 正确格式
    "Accept":       "application/json",
}

print("=" * 70)
print("Jupiter API Key 认证方式: x-api-key 头")
print(f"Key: {API_KEY[:8]}...{API_KEY[-4:]}")
print("=" * 70)

# ── 测试1: Quote API (Basic Plan 路径)──────────────────────────
print("\n[1] GET /swap/v1/quote ...")
try:
    r = httpx.get(
        "https://api.jup.ag/swap/v1/quote",
        params={
            "inputMint":   "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "outputMint":  "So11111111111111111111111111111111111111112",
            "amount":      "100000000",   # 100 USDC
            "slippageBps": "50",
        },
        headers=HEADERS,
        verify=False,
        timeout=20,
    )
    print(f"    HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        out = int(d.get("outAmount", 0)) / 1e9
        pi  = d.get("priceImpactPct", "N/A")
        dexs= [s.get("swapInfo", {}).get("label", "?") for s in d.get("routePlan", [])[:3]]
        print(f"    ✅ 成功！买入 100 USDC → {out:.4f} SOL")
        print(f"    价格冲击: {pi}")
        print(f"    路由: {' → '.join(dexs)}")
    else:
        print(f"    ❌ {r.text[:300]}")
except Exception as e:
    print(f"    ❌ 错误: {e}")

time.sleep(1.2)   # 遵守 1 RPS

# ── 测试2: Price API ─────────────────────────────────────────
print("\n[2] GET /price/v2 ...")
try:
    r = httpx.get(
        "https://api.jup.ag/price/v2",
        params={"ids": "So11111111111111111111111111111111111111112,EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
        headers=HEADERS,
        verify=False,
        timeout=15,
    )
    print(f"    HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json().get("data", {})
        for mint, info in d.items():
            sym = "SOL" if "11111" in mint else "USDC"
            print(f"    ✅ {sym}: ${info.get('price')}")
    else:
        print(f"    ❌ {r.text[:300]}")
except Exception as e:
    print(f"    ❌ 错误: {e}")

time.sleep(1.2)

# ── 测试3: Ultra 端点 ─────────────────────────────────────────
print("\n[3] GET /ultra/v1/quote (Ultra Beta)...")
try:
    r = httpx.get(
        "https://api.jup.ag/ultra/v1/quote",
        params={
            "inputMint":  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "outputMint": "So11111111111111111111111111111111111111112",
            "amount":     "100000000",
        },
        headers=HEADERS,
        verify=False,
        timeout=20,
    )
    print(f"    HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        print(f"    ✅ Ultra 成功! outAmount: {d.get('outAmount')}")
    else:
        print(f"    ❌ {r.text[:300]}")
except Exception as e:
    print(f"    ❌ 错误: {e}")

print("\n" + "=" * 70)
