# Base Builder Grant Nomination: x402 Agent Tollbooth

**Project Categories:** 
- Application Developers Shipping on Base Mainnet
- Developer Tooling

## Project Overview
The x402 Agent Tollbooth is an experimental, production-ready infrastructure enabling autonomous machine-to-machine (M2M) commerce on the Base network. By acting as an API gateway for high-value technical schemas and developer tooling, the tollbooth demonstrates how AI agents and automated systems can transact natively using USDC on Base.

## Core Architectural Achievements

### 1. Live Deployment & x402-Gated API Integration
The system is actively deployed on Render as a high-conversion, multi-schema monetization hub. It employs a Freemium Preview Protocol to serve schema metadata to LLMs, followed by an explicit `x-402-payment-required` HTTP challenge that dictates exactly how agents can purchase the full un-truncated datasets.

### 2. Native Base Mainnet Integration (USDC)
The tollbooth natively verifies transactions on the Base mainnet. When an AI agent receives the HTTP 402 challenge, it is instructed to execute a transfer of exactly 1.00 USDC (1,000,000 base units) to the recipient wallet (`0x73279fa4BadA7CAC888c62CDa4f5c8104765f6f1`) using the Base USDC Contract (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`). The client then resubmits its request with the `X-PAYMENT` header containing the transaction hash for validation.

### 3. Cryptographic Replay-Attack Protection
Security and transaction integrity are maintained via strict on-chain receipt validation. When the `X-PAYMENT` header is submitted, the system connects to the public Base RPC (`https://mainnet.base.org`), pulls the receipt, and validates the following:
- The transaction status succeeded (`status == 1`).
- The `to` address strictly matches the Base USDC contract.
- The transaction logs contain the precise ERC-20 `Transfer` topic.
- The decoded transfer logs confirm the exact recipient and exact requested amount.
- An integrated SQLite backend caches transactions and prevents double-spend exploits, returning a `409 Conflict` for any previously redeemed transaction hashes.

## Ecosystem Impact & Public Good
This infrastructure serves as an experimental public good for the Base ecosystem. By proving that automated AI agents can successfully interpret HTTP 402 challenges and negotiate micro-payments autonomously on Base, it paves the way for a new standard in machine-to-machine commerce, API monetization, and decentralized AI developer tooling on-chain.
