import requests, json, warnings
warnings.filterwarnings("ignore")

proxies = {"https": "http://127.0.0.1:7897", "http": "http://127.0.0.1:7897"}

# 测试1: Jupiter Quote API
print("=== Test 1: Jupiter Quote API ===")
try:
    r = requests.get(
        "https://quote-api.jup.ag/v6/quote",
        params={
            "inputMint":  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "outputMint": "So11111111111111111111111111111111111111112",
            "amount":     "10000000",
            "slippageBps":"50"
        },
        proxies=proxies, verify=False, timeout=15
    )
    print(f"Status: {r.status_code}")
    d = r.json()
    out_amount = d.get("outAmount", "N/A")
    routes = len(d.get("routePlan", []))
    print(f"outAmount: {out_amount} (SOL lamports)")
    print(f"Routes: {routes}")
    if out_amount != "N/A":
        sol_out = int(out_amount) / 1e9
        print(f"  => 10 USDC = {sol_out:.6f} SOL")
except Exception as e:
    print(f"Error: {e}")

# 测试2: 反向查询 SOL→USDC
print("\n=== Test 2: SOL → USDC ===")
try:
    # 先算刚才得到的SOL量再查回来
    r2 = requests.get(
        "https://quote-api.jup.ag/v6/quote",
        params={
            "inputMint":  "So11111111111111111111111111111111111111112",
            "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount":     str(int(out_amount)) if out_amount != "N/A" else "62000000",
            "slippageBps":"50"
        },
        proxies=proxies, verify=False, timeout=15
    )
    d2 = r2.json()
    usdc_back = int(d2.get("outAmount", 0)) / 1e6
    print(f"SOL back to USDC: {usdc_back:.4f} USDC")
    profit = usdc_back - 10.0
    print(f"Round-trip profit: ${profit:+.4f} ({profit/10*100:+.3f}%)")
except Exception as e:
    print(f"Error: {e}")

# 测试3: Kamino APY
print("\n=== Test 3: Kamino Finance ===")
try:
    r3 = requests.get(
        "https://api.kamino.finance/strategies/allTokens/metrics",
        proxies=proxies, verify=False, timeout=10
    )
    print(f"Kamino Status: {r3.status_code}")
    if r3.status_code == 200:
        data = r3.json()
        for item in (data if isinstance(data, list) else [])[:5]:
            print(f"  {item.get('symbol')}: APY={item.get('apy')}")
except Exception as e:
    print(f"Kamino Error: {e}")
