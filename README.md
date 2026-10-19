# 🛣️ x402 Agent Tollbooth

The **x402 Agent Tollbooth** is an enterprise-grade Model Context Protocol (MCP) server that demonstrates machine-to-machine (M2M) micro-transactions on the **Base** network. 

This project provides an infrastructure layer allowing AI agents to programmatically access specialized Web3 intelligence and smart contract analysis tools by fulfilling automated HTTP 402 (Payment Required) workflows via the x402 protocol standard. Agents pay per tool execution directly in USDC, enabling a seamless, trustless API monetization model.

![Smithery Quality Score: 100/100](https://img.shields.io/badge/Smithery_Quality-100%2F100-success)
![Network](https://img.shields.io/badge/Network-Base-blue)
![Currency](https://img.shields.io/badge/Currency-USDC-2775CA)
[![Glama](https://glama.ai/mcp/servers/ak10082247-max/x402-agent-tollbooth/badges/score.svg)](https://glama.ai/mcp/servers/ak10082247-max/x402-agent-tollbooth)

---

## 💻 Open Source Implementation & Self-Hosting

This repository contains the **full, open-source Python implementation** of the MCP server. The server is built using the official `mcp` SDK and `sse-starlette` to handle Server-Sent Events (SSE) and JSON-RPC tool calling. 

The core implementation is located in [`tollbooth_agent.py`](tollbooth_agent.py).

### Running from Source (Local Execution)
You can easily self-host this MCP server or run it locally for your own agents.

**Using Docker:**
```bash
docker build -t x402-tollbooth .
docker run -p 8000:8000 -e GEMINI_API_KEY="your_api_key" x402-tollbooth
```

**Using Python:**
```bash
pip install -r requirements.txt
uvicorn tollbooth_agent:mcp_app --host 0.0.0.0 --port 8000
```

---

## 🛠️ Server Capabilities

This server exposes a navigable tree of specialized Web3 tools. AI agents must provide a valid Base network `paymentHash` (transaction receipt) for the exact USDC amount required to execute the paid tools.

**🤝 Referral Revenue Sharing Protocol:** The server implements an optional `referralWallet` parameter. AI agents acting as intermediaries can append their wallet address to receive a 20% protocol fee distribution. 

### 🆓 Infrastructure & Discovery
*   `contract.auditTeaser` **(FREE)**: Scans a Base smart contract for vulnerabilities and returns a high-level summary. Designed to allow agents to assess necessity before authorizing paid deep-dives.

### 📊 Token Data & Intelligence
*   `token.analyze` **(0.50 USDC)**: Real-time liquidity, volume, and analytics for any Base token. Aggregates data for high-frequency algorithmic usage.

### 🔐 Smart Contract Security
*   `contract.audit` **(1.00 USDC)**: Full AI-driven smart contract vulnerability audit. Returns exact lines of code, risk severity, and attack vectors.
*   `contract.patch` **(5.00 USDC)**: Premium service. Audits the contract and generates production-ready, secure Solidity code to patch the vulnerabilities.

### 🧠 Market Intelligence
*   `market.alpha` **(10.00 USDC)**: High-level metadata brokering. Aggregates metadata to reveal which smart contracts are currently experiencing high automated analysis volume on the network.
*   `wallet.profile` **(2.00 USDC)**: Behavioral finance AI analysis of a specific wallet address. Generates risk profiles and portfolio strategies based on public on-chain actions.

### 💾 Agent Persistence
*   `memory.store` **(0.01 USDC)**: Persistent memory bank for agents to store context across sessions.
*   `memory.retrieve` **(0.01 USDC)**: Retrieve stored contextual memory.
*   `llm.query` **(0.10 USDC)**: Query the Tollbooth's underlying LLM directly for complex reasoning tasks.

---

## ⚡ The X402 FastPass SDK (Seamless Agent Integration)

If you are building custom AI agents in LangChain, AutoGen, or CrewAI, you do **not** need to teach your LLMs how to write Web3 transactions to use this server.

We have included the **X402 FastPass SDK** (`x402_fastpass.py`) directly in this repository. It acts as a wrapper around the MCP client and automatically handles the USDC crypto payments natively in Python.

**How to give your agent seamless access:**
```python
from x402_fastpass import X402FastPass
import asyncio

# 1. Give the FastPass Client your agent's Base wallet private key
client = X402FastPass(private_key="0xYOUR_PRIVATE_KEY")

# 2. Give this Python function to your agent as a standard tool.
# The SDK automatically handles the on-chain USDC transfer and passes the payment hash to the MCP server!
async def run_audit():
    result = await client.audit_contract("0xTargetSmartContractAddress")
    print(result)

asyncio.run(run_audit())
```
*Note: The FastPass SDK automatically injects your agent's wallet address as the `referralWallet`, meaning your agent automatically earns a 20% cashback on all tools it calls!*

---

## ⚙️ How it Works: Modern x402 V2 Header Handshake (100% Gasless)

The server supports the official x402 V2 specification with **100% gasless settlement** on Base Mainnet (`eip155:8453`) and Solana Mainnet (`solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp`):

1. **Unpaid Probe**: Agent calls endpoint (e.g. `POST /toll/cross-dex-arbitrage`). Server immediately returns `HTTP 402 Payment Required` with a **50% Free Teaser Preview** and `PAYMENT-REQUIRED` header challenge.
2. **Auto-Sign (Zero Gas)**: Agent signs an EIP-712 `TransferWithAuthorization` (on Base) or partially-signs an SPL `TransferChecked` (on Solana). The relayer facilitator sponsors all gas fees ($0 ETH / $0 SOL required).
3. **Replay & Unlock**: Agent attaches Base64 `PAYMENT-SIGNATURE` header. Server verifies via facilitator in <10ms and returns `HTTP 200 OK` with full unredacted intel and `PAYMENT-RESPONSE` cryptographic receipt.

### Autonomous Agent Auto-Pay (Python)

```python
import base64, json, secrets, time, requests
from eth_account import Account
from eth_account.messages import encode_typed_data

def paid_toll_call(endpoint: str, payload: dict, private_key: str):
    account = Account.from_key(private_key)
    url = f"https://x402-agent-tollbooth.onrender.com{endpoint}"

    # 1. Probe endpoint
    res = requests.post(url, json=payload)
    if res.status_code == 200:
        return res.json()

    # 2. Decode 402 challenge & sign EIP-712 authorization
    raw_pr = res.headers.get("PAYMENT-REQUIRED") or res.headers.get("X-Payment-Required")
    pr_json = json.loads(base64.b64decode(raw_pr).decode("utf-8"))
    accepted = next(a for a in pr_json["accepts"] if "8453" in str(a.get("network", "")))

    now = int(time.time())
    nonce = secrets.token_bytes(32)
    types = {"TransferWithAuthorization": [
        {"name": "from", "type": "address"}, {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"}, {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"}, {"name": "nonce", "type": "bytes32"},
    ]}
    domain = {"name": "USD Coin", "version": "2", "chainId": 8453, "verifyingContract": accepted["asset"]}
    msg = {"from": account.address, "to": accepted["payTo"], "value": int(accepted["amount"]), "validAfter": 0, "validBefore": now + 300, "nonce": nonce}
    sig = account.sign_message(encode_typed_data(domain_data=domain, message_types=types, message_data=msg)).signature.hex()

    payment_b64 = base64.b64encode(json.dumps({
        "x402Version": 2, "resource": pr_json.get("resource"), "accepted": accepted,
        "payload": {"signature": "0x" + sig.lstrip("0x"), "authorization": {
            "from": account.address, "to": accepted["payTo"], "value": str(accepted["amount"]),
            "validAfter": "0", "validBefore": str(now + 300), "nonce": "0x" + nonce.hex()
        }}
    }).encode()).decode()

    # 3. Settle & unlock premium response
    paid_res = requests.post(url, json=payload, headers={"PAYMENT-SIGNATURE": payment_b64})
    return paid_res.json()
```

---

## 🚀 Connecting to the Hosted Endpoint

If you do not want to run the server from source, connect directly to our public hosted endpoint:

* **Remote MCP URL**: `https://x402-agent-tollbooth.onrender.com/mcp`
* **Discovery Manifest**: `https://x402-agent-tollbooth.onrender.com/.well-known/mcp/server-card.json`
* **x402 Manifest**: `https://x402-agent-tollbooth.onrender.com/.well-known/x402.json`
* **Smithery CLI Install**:
```bash
npx @smithery/cli mcp install x402-agent-tollbooth
```
