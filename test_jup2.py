import httpx, json

proxies = "http://127.0.0.1:7897"

# 测试1: Jupiter Quote API
print("=== Test 1: Jupiter Quote API (USDC->SOL) ===")
try:
    with httpx.Client(proxy=proxies, verify=False, timeout=15) as client:
        r = client.get(
            "https://quote-api.jup.ag/v6/quote",
            params={
                "inputMint":  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "outputMint": "So11111111111111111111111111111111111111112",
                "amount":     "10000000",
                "slippageBps":"50"
            }
        )
        print(f"Status: {r.status_code}")
        d = r.json()
        out_amount = d.get("outAmount", 0)
        routes = len(d.get("routePlan", []))
        print(f"outAmount raw: {out_amount} lamports")
        print(f"Routes: {routes}")
        sol_out = int(out_amount) / 1e9
        print(f"=> 10 USDC = {sol_out:.6f} SOL")

        # 测试2: 反向 SOL->USDC
        print("\n=== Test 2: SOL -> USDC (round trip) ===")
        r2 = client.get(
            "https://quote-api.jup.ag/v6/quote",
            params={
                "inputMint":  "So11111111111111111111111111111111111111112",
                "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount":     str(out_amount),
                "slippageBps":"50"
            }
        )
        d2 = r2.json()
        usdc_back = int(d2.get("outAmount", 0)) / 1e6
        profit = usdc_back - 10.0
        print(f"USDC back: {usdc_back:.4f}")
        print(f"Profit: ${profit:+.4f} ({profit/10*100:+.3f}%)")

except Exception as e:
    print(f"Jupiter Error: {e}")

# 测试3: Jupiter USDC->JUP->USDC
print("\n=== Test 3: USDC->JUP->USDC ===")
try:
    with httpx.Client(proxy=proxies, verify=False, timeout=15) as client:
        r = client.get("https://quote-api.jup.ag/v6/quote", params={
            "inputMint":  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "outputMint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
            "amount": "10000000", "slippageBps": "50"
        })
        jup_amount = r.json().get("outAmount", 0)
        r2 = client.get("https://quote-api.jup.ag/v6/quote", params={
            "inputMint":  "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
            "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": str(jup_amount), "slippageBps": "50"
        })
        usdc_back = int(r2.json().get("outAmount", 0)) / 1e6
        profit = usdc_back - 10.0
        print(f"USDC back: {usdc_back:.4f}  Profit: ${profit:+.4f} ({profit/10*100:+.3f}%)")
except Exception as e:
    print(f"JUP arb Error: {e}")

# 测试4: Jupiter Price API
print("\n=== Test 4: Token Prices ===")
try:
    with httpx.Client(proxy=proxies, verify=False, timeout=10) as client:
        r = client.get("https://api.jup.ag/price/v2", params={
            "ids": "So11111111111111111111111111111111111111112,EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        })
        print(f"Price API status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            for mint, info in data.get("data", {}).items():
                print(f"  {mint[:10]}...: ${info.get('price')}")
        else:
            print(f"Response: {r.text[:200]}")
except Exception as e:
    print(f"Price Error: {e}")
