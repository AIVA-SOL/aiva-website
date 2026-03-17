import httpx

# 不走代理，直连测试
print("=== 直连测试（不走代理）===")
try:
    r = httpx.get(
        "https://quote-api.jup.ag/v6/quote",
        params={
            "inputMint":  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "outputMint": "So11111111111111111111111111111111111111112",
            "amount":     "10000000",
            "slippageBps":"50"
        },
        verify=False, timeout=10
    )
    print(f"Status: {r.status_code}")
    d = r.json()
    out = d.get("outAmount", 0)
    print(f"outAmount: {out}  => {int(out)/1e9:.6f} SOL")
except Exception as e:
    print(f"Error: {e}")
