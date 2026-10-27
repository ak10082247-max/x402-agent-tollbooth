# Paid fulfillment and quote verification

The four protected routes and HTTP MCP `tools/call` share one executor. Prices and payment networks remain defined in `TOLL_ENDPOINTS`. Quote analysis can use Base or Solana independently of the network used to pay.

- `/toll/arbitrage_scan`: exact human amount of the first token in `pair`; `chain: base` or `solana`. Base returns independently acquired two-leg quotes from distinct reviewed pools at one block. Solana acquires both legs from Raydium, binds the second input to the first output, and excludes shared-pool paths from independent-route candidates. Neither reports net profitability when execution costs are unproven.
- `/toll/smart_router`: binds `tokenIn`, `tokenOut`, `amount`, `chain` and on-chain decimals. Base chooses the best acquired direct quote; Solana returns Raydium's acquired route. It does not claim global or split-route optimality.
- `/toll/ai_intel`: reviews supplied source or verified Base contract source. With `GEMINI_API_KEY` and an available `AUDIT_MODEL`, it requests model analysis. Otherwise, source indicators are explicitly limited pattern review, never a safe verdict.
- `/api/audit`: requires an exact Base `contractAddress`, acquires all verified Sourcify v2 source files, and runs the same source analysis. Missing source/provider failures return 503 before settlement. `isPatch: true` requires the model provider. No source is silently truncated.

Input validation and result acquisition happen before settlement. Failure during acquisition reports `charged: false`. Base EIP-3009 signatures and sponsored Solana buyer signatures are locally checked. A read-only PayAI `/verify` call validates authorization and available funding before provider or AI acquisition, independently of the later settlement call. PayAI's `/supported` advertises x402 v2 exact for both mainnets. The server enforces its exact quote, recipient, resource and network; Solana overpayment is not selected from client metadata.

SQLite atomically binds an authorization identity to the exact tool and arguments, stores the acquired result before settlement, and records the complete confirmed receipt. Retrying the identical signed authorization recovers an already delivered result without settling again. Changing its arguments is a conflict. A timeout, malformed settlement receipt, or interrupted `settling` state requires independent reconciliation; the server does not automatically charge again or invent success. Automatic reconciliation/refunds are not implemented. The cached result is confidential to possession of the same signed authorization; do not share authorization headers.

Set `PAYMENTS_DB_PATH` to an absolute path **on a persistent volume**. The default `payments.db` beside the code survives process restarts on that filesystem, but Render's default ephemeral filesystem does not preserve it across replacement/deployment. The checked-in Render blueprint has no persistent disk; durable cross-deployment recovery is not proven until the host supplies this volume. No billable disk plan was added automatically.

`BASE_RPC_URL` and `SOLANA_RPC_URL` may configure providers; public mainnet fallbacks exist. RPC URLs and provider exceptions are not returned in responses, and HTTP request logging is suppressed because URLs may contain keys. Base quote state includes block number/hash; Solana mint metadata includes its slot, while Raydium provider quotes are explicitly not pinned to that slot. Provider responses are not guarantees of fills, simulation, transfer-tax behavior or profit. No swap transaction is built or submitted.

`/version` reports `RENDER_GIT_COMMIT` or `GIT_COMMIT` for deployment verification. Health is process health, not a paid route/provider pass.

The legacy direct-transfer dapp now signs the exact 0.02-USDC x402 authorization and retains it for same-page recovery. A bare `paymentHash` does not buy a new unbound audit. The formerly fabricated Solana Blink reports and static live-alert feed are explicitly unavailable; the Blink route constructs no transaction and takes no payment. Use protected HTTP MCP/API or the Base dapp. Local owned stdio runs the read-only core freely; hosted SSE returns a payment challenge and directs clients to HTTP for per-call authorization.

Verification:

```powershell
python -m unittest discover -s tests -v
```

The tests use deterministic unfunded fixture keys, mocked facilitators and provider contracts. They make no paid requests, read no funded wallet keys and submit no transactions. Separate recorded public-provider smoke tests verify live Base quotes, Solana Raydium quotes, and Sourcify source acquisition; they are not live paid settlement tests or a production deployment certificate.
