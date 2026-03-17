"""测试 Jupiter API Key 是否生效"""
import httpx
import json

API_KEY = "69175f3b-d09d-4005-8b3a-4a9b27a09cf8"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

print("=" * 60)
print("Jupiter API Key 验证测试")
print(f"Key: {API_KEY[:8]}...{API_KEY[-4:]}")
print("=" * 60)

# 测试1: Price API
print("\n[1] Price API v2 ...")
try:
    r = httpx.get(
        "https://api.jup.ag/price/v2",
        params={"ids": "So11111111111111111111111111111111111111112"},
        headers=HEADERS,
        verify=False,
        timeout=15,
    )
    print(f"    状态: HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        sol_price = d.get("data", {}).get("So11111111111111111111111111111111111111112", {}).get("price")
        print(f"    ✅ SOL 价格: ${sol_price}")
    else:
        print(f"    响应: {r.text[:200]}")
except Exception as e:
    print(f"    ❌ 错误: {e}")

# 测试2: Quote API
print("\n[2] Quote API (swap/v1/quote) ...")
try:
    r = httpx.get(
        "https://api.jup.ag/swap/v1/quote",
        params={
            "inputMint":  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "outputMint": "So11111111111111111111111111111111111111112",
            "amount":     "100000000",  # 100 USDC
            "slippageBps": "50",
        },
        headers=HEADERS,
        verify=False,
        timeout=15,
    )
    print(f"    状态: HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        print(f"    ✅ outAmount: {d.get('outAmount')}")
        print(f"    路由: {[s.get('swapInfo',{}).get('label','?') for s in d.get('routePlan',[])[:3]]}")
    else:
        print(f"    响应: {r.text[:300]}")
except Exception as e:
    print(f"    ❌ 错误: {e}")

# 测试3: 不带Key
print("\n[3] Quote API（不带Key，对照）...")
try:
    r = httpx.get(
        "https://api.jup.ag/swap/v1/quote",
        params={
            "inputMint":  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "outputMint": "So11111111111111111111111111111111111111112",
            "amount":     "100000000",
        },
        verify=False,
        timeout=15,
    )
    print(f"    状态: HTTP {r.status_code}")
    print(f"    响应: {r.text[:200]}")
except Exception as e:
    print(f"    ❌ 错误: {e}")

print("\n" + "=" * 60)
