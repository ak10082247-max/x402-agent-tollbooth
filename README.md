# 🛣️ x402 Agent Tollbooth

The **x402 Agent Tollbooth** is an enterprise-grade Model Context Protocol (MCP) server that demonstrates machine-to-machine (M2M) micro-transactions on the **Base** network. 

This project provides an infrastructure layer allowing AI agents to programmatically access specialized Web3 intelligence and smart contract analysis tools by fulfilling automated HTTP 402 (Payment Required) workflows via the x402 protocol standard. Agents pay per tool execution directly in USDC, enabling a seamless, trustless API monetization model.

![Smithery Quality Score: 100/100](https://img.shields.io/badge/Smithery_Quality-100%2F100-success)
![Network](https://img.shields.io/badge/Network-Base-blue)
![Currency](https://img.shields.io/badge/Currency-USDC-2775CA)

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

## ⚙️ How it Works (x402 Protocol)
1.  The AI Agent initiates a tool call, providing required inputs (e.g., `contractAddress`).
2.  The Agent executes an on-chain transaction sending the exact USDC amount to the specified service wallet (`0x73279fa4BadA7CAC888c62CDa4f5c8104765f6f1`).
3.  The Agent passes the transaction hash via the `paymentHash` argument.
4.  The server verifies the transaction on BaseScan.
5.  Upon successful verification, the server executes the capability and returns the requested JSON payload.

## 🚀 Connecting to the Hosted Endpoint
If you do not want to run the server from source, you can connect directly to our public hosted endpoint. 

Compatible with standard MCP clients (Claude Desktop, Cursor) and indexed on [Smithery](https://smithery.ai/).

```bash
npx @smithery/cli mcp install x402-agent-tollbooth
```
