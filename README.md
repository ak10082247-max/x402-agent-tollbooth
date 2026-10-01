# 🛣️ x402 Agent Tollbooth

The first fully autonomous, crypto-monetized Model Context Protocol (MCP) server built on the **Base** network. 

**x402 Agent Tollbooth** allows AI agents to access premium, high-value Web3 intelligence and smart contract analysis tools using the x402 machine-to-machine micro-transaction protocol. Agents pay for exactly what they use, directly in USDC.

![Smithery Quality Score: 100/100](https://img.shields.io/badge/Smithery_Quality-100%2F100-success)
![Network](https://img.shields.io/badge/Network-Base-blue)
![Currency](https://img.shields.io/badge/Currency-USDC-2775CA)

## 🛠️ Available Capabilities

This server exposes a navigable tree of specialized Web3 tools. AI agents must provide a valid Base network `paymentHash` (transaction receipt) for the exact USDC amount required to execute the tool.

### 🆓 Freemium & Discovery
*   `contract.auditTeaser` **(FREE)**: Scans a Base smart contract for vulnerabilities and returns a high-level summary (e.g., "1 critical risk found"). Designed to allow agents to discover risks before authorizing paid deep-dives.

### 🔐 Smart Contract Tools
*   `contract.audit` **(1.00 USDC)**: Full AI-driven smart contract vulnerability audit. Returns exact lines of code, risk severity, and attack vectors.
*   `contract.patch` **(5.00 USDC)**: Premium service. Not only audits the contract but generates production-ready, secure Solidity code to patch the vulnerabilities.

### 🧠 Market Intelligence
*   `market.alpha` **(10.00 USDC)**: High-ticket data brokering. Aggregates metadata to reveal exactly which smart contracts and wallets other AI agents on the network are currently analyzing, giving trading bots a front-running advantage.
*   `wallet.profile` **(2.00 USDC)**: Behavioral finance AI analysis of a specific wallet address. Generates psychological risk profiles and token accumulation strategies based on on-chain heuristics.

### 💾 Agent Infrastructure
*   `memory.store` **(0.01 USDC)**: Persistent memory bank for agents to store context across sessions.
*   `memory.retrieve` **(0.01 USDC)**: Retrieve stored contextual memory.
*   `llm.query` **(0.10 USDC)**: Intelligence arbitrage. Query the Tollbooth's underlying premium LLM directly for complex reasoning tasks.

## ⚙️ How it Works (x402 Protocol)

1.  The Client AI Agent discovers the Tollbooth tools via MCP (Model Context Protocol).
2.  The Agent calls a tool, providing the required inputs (e.g., `contractAddress`).
3.  If the tool is premium, the Agent executes an on-chain transaction sending the exact USDC amount to the Tollbooth Wallet (`0x73279fa4BadA7CAC888c62CDa4f5c8104765f6f1`).
4.  The Agent passes the transaction hash via the `paymentHash` argument.
5.  The Tollbooth verifies the transaction on BaseScan.
6.  Upon successful verification, the Tollbooth executes the capability and returns the premium JSON data to the Agent.

## 🚀 Installation & Usage

This server is fully compatible with any standard MCP client (Claude Desktop, Cursor, Agent frameworks) and is indexed on [Smithery](https://smithery.ai/).

```bash
# Example Smithery deployment
npx @smithery/cli mcp install x402-agent-tollbooth
```

Built for the autonomous AI economy.
