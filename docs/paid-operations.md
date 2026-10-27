# Paid analysis operations

All HTTP and MCP purchases acquire and retain the requested result before one
settlement attempt. An identical signed retry recovers a delivered purchase. A
different request using the same authorization is rejected. Never automatically
submit a second payment to recover an ambiguous settlement.

Set `PAYMENTS_DB_PATH` to a persistent, writable SQLite file shared by the service's
workers. An instance's ephemeral filesystem does not survive redeployment. Separate
replicas with independent files do not share the authorization journal. Configure a
persistent mount and one service instance, or supply a reviewed shared-store adapter
before scaling across hosts. Back up the journal; do not reset it between deployments.

Unpaid preparation has a 120-second lease. Recovery assigns a new owner. The paused
worker must pass an owner-checked compare-and-swap before settlement and cannot
charge after its preparation was reclaimed. `settling` and `settlement_unknown`
states are never reclaimed on elapsed time alone.

## Model availability and operating costs

The AI endpoints require a configured model. Without one they fail before charging.
`limited_review: true` explicitly purchases a source-pattern review at that endpoint's
quoted price. The schema, response and receipt disclose that limited method; it is
not an AI audit or a patch. Patch requests require the model.

The exact default `gemini-2.5-flash` model has a named standard paid text-price
profile verified on 2026-10-27: USD 0.30 per million input tokens and USD 2.50 per
million output tokens including thinking. Source:
https://ai.google.dev/gemini-api/docs/pricing . This does not prove model access or
free-tier eligibility. Other models require both `AUDIT_INPUT_USD_PER_MILLION` and
`AUDIT_OUTPUT_USD_PER_MILLION`; operator overrides must match actual provider billing.
Recheck rates when changing models or billing plans.

Before generation, the service counts input tokens and reduces `max_output_tokens`
to fit at most half of the endpoint's gross price. Thinking is explicitly disabled
for the default model and any reported thinking usage is still counted. Configure
`AUDIT_MAX_OUTPUT_TOKENS` (64–8192, default 2048) and optionally reduce
`AUDIT_MAX_PROVIDER_COST_RATIO` (positive, maximum 0.5). Oversized input fails before
generation or settlement. Large verified contracts can exceed a low-price SKU's
allowance; do not silently truncate source or sell a partial review as complete.

`provider_cost_events` retains a reservation before generation, including when the
provider times out. If usage is returned it records input, output and thinking counts
with the configured-rate cost estimate, including invalid model JSON or over-budget
results that are not sold. `provider_usage.cost_event_id` joins successful model
results to these operating-cost records. A reservation with unknown usage is not
zero cost. These figures exclude hosting, facilitator charges and other expenses;
they do not establish accounting profit or confirmed customer revenue.

## Recover a settled purchase

An owner runs this command on the host with the correct persistent journal:

```text
python scripts/reconcile_paid_operation.py --payment-file original-public-payment-header.txt --tool arbitrage_scan --transaction ACTUAL_TRANSACTION
```

The file contains the original `PAYMENT-SIGNATURE` header, never a wallet private key.
The command accepts only a retained operation that matches its signed authorization.
It makes allowlisted read-only RPC requests and submits zero settlements. It requires:

- Base mainnet: finalized successful transaction, canonical block hash, exact USDC
  buyer debit and merchant credit, and that authorization's `AuthorizationUsed` nonce.
- Solana mainnet: finalized successful transaction, exact original signed message,
  matching transaction signature, and exact USDC buyer debit and merchant credit.

On validated proof it atomically marks the retained result delivered. The customer
then retries the same signed request. Missing, substituted, unsuccessful or
unfinalized evidence leaves the operation quarantined. Keep the journal private;
this operator command is not exposed as an unauthenticated HTTP route. It cannot
resolve a transaction whose identity is unknown or prove an absent transaction was
never broadcast.
