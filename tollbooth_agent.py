import os
import json
import sqlite3
import uvicorn
from typing import Optional
from fastapi import FastAPI, Request, Query, Header, HTTPException, Response
from fastapi.responses import PlainTextResponse, JSONResponse
from web3 import Web3

USDC_CONTRACT_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WALLET_ADDRESS = "0x73279fa4BadA7CAC888c62CDa4f5c8104765f6f1"
EXPECTED_AMOUNT = 1000000  # 1.00 USDC, 6 decimals
TRANSFER_EVENT_SIGNATURE = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

app = FastAPI(
    title="x402 Agent Tollbooth - API Fix Engine",
    version="2.0.0",
    description="High-conversion, multi-schema monetization hub with programmatic SEO and Web3 on-chain payment verification."
)

w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))

def init_db():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS payments (tx_hash TEXT PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

# Mocked 25 records for each dataset
def generate_catalog(name: str):
    return [{"id": i, "project": name, "change": f"Fix {i} for {name}", "diff": "+ config", "severity": "high"} for i in range(1, 26)]

CATALOGS = {
    "deprecation_fixes_2026": generate_catalog("deprecation_fixes_2026"),
    "react19_nextjs_migrations": generate_catalog("react19_nextjs_migrations"),
    "stripe_billing_v2_fixes": generate_catalog("stripe_billing_v2_fixes"),
    "web3_evm_migrations": generate_catalog("web3_evm_migrations")
}

def verify_payment(tx_hash: str):
    try:
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute('SELECT tx_hash FROM payments WHERE tx_hash=?', (tx_hash,))
        if c.fetchone():
            conn.close()
            return "ALREADY_REDEEMED"
        
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if not receipt or receipt.get("status") != 1:
            conn.close()
            return False
            
        if receipt["to"].lower() != USDC_CONTRACT_ADDRESS.lower():
            conn.close()
            return False
            
        is_valid = False
        for log in receipt["logs"]:
            if len(log["topics"]) > 0 and log["topics"][0].hex() == TRANSFER_EVENT_SIGNATURE:
                if len(log["topics"]) == 3:
                    to_address = "0x" + log["topics"][2].hex()[26:]
                    if to_address.lower() == WALLET_ADDRESS.lower():
                        data = log["data"]
                        value = int(data, 16) if isinstance(data, str) else int(data.hex(), 16)
                        if value == EXPECTED_AMOUNT:
                            is_valid = True
                            break
        
        if is_valid:
            c.execute('INSERT INTO payments (tx_hash) VALUES (?)', (tx_hash,))
            conn.commit()
        conn.close()
        return is_valid
    except Exception as e:
        print(f"Verification error: {e}")
        return False

@app.on_event("startup")
async def startup_event():
    init_db()

@app.get("/llms.txt", response_class=PlainTextResponse)
async def get_llms():
    if os.path.exists("llms.txt"):
        with open("llms.txt", "r") as f:
            return f.read()
    return "Not found"

@app.get("/robots.txt", response_class=PlainTextResponse)
async def get_robots():
    return "User-agent: *\nAllow: /\nSitemap: https://x402-agent-tollbooth.onrender.com/sitemap.xml"

@app.get("/sitemap.xml")
async def get_sitemap():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://x402-agent-tollbooth.onrender.com/v1/schema/deprecation_fixes_2026.json</loc></url>
  <url><loc>https://x402-agent-tollbooth.onrender.com/v1/schema/react19_nextjs_migrations.json</loc></url>
  <url><loc>https://x402-agent-tollbooth.onrender.com/v1/schema/stripe_billing_v2_fixes.json</loc></url>
  <url><loc>https://x402-agent-tollbooth.onrender.com/v1/schema/web3_evm_migrations.json</loc></url>
  <url><loc>https://x402-agent-tollbooth.onrender.com/errors/nextjs-turbopack-action-error</loc></url>
  <url><loc>https://x402-agent-tollbooth.onrender.com/errors/stripe-webhook-signature-verification-failed</loc></url>
  <url><loc>https://x402-agent-tollbooth.onrender.com/errors/base-evm-blob-fee-error</loc></url>
  <url><loc>https://x402-agent-tollbooth.onrender.com/llms.txt</loc></url>
</urlset>'''
    return Response(content=xml, media_type="application/xml")

@app.get("/errors/{error_name}", response_class=PlainTextResponse)
async def get_error_page(error_name: str):
    mapping = {
        "nextjs-turbopack-action-error": "react19_nextjs_migrations",
        "stripe-webhook-signature-verification-failed": "stripe_billing_v2_fixes",
        "base-evm-blob-fee-error": "web3_evm_migrations"
    }
    catalog = mapping.get(error_name, "deprecation_fixes_2026")
    content = f"""Error: {error_name}
Description: Resolution and fixes for {error_name}.
Sample Fix: "change": "Apply proper config or updated SDK method."
Full Fix Schema: https://x402-agent-tollbooth.onrender.com/v1/schema/{catalog}.json
"""
    return content

@app.get("/v1/schema/{dataset_name}.json")
async def get_schema(request: Request, dataset_name: str, full: Optional[bool] = Query(False)):
    if dataset_name not in CATALOGS:
        return JSONResponse(status_code=404, content={"detail": "Catalog not found"})

    receipt_hash = request.headers.get("x-payment")
    
    # Paid GET logic
    if receipt_hash:
        status = verify_payment(receipt_hash)
        if status == "ALREADY_REDEEMED":
            return JSONResponse(status_code=409, content={"error": "Transaction hash already redeemed"})
        elif status == True:
            return JSONResponse(content=CATALOGS[dataset_name])
        else:
            return JSONResponse(status_code=400, content={"detail": "Invalid or missing payment transfer"})
            
    # Challenge GET logic
    if full:
        headers = {
            "x-402-payment-required": "true",
            "x-402-token": "USDC",
            "x-402-network": "base",
            "x-402-amount": "1000000",
            "x-402-recipient": WALLET_ADDRESS
        }
        return JSONResponse(status_code=402, content={"detail": "Payment Required"}, headers=headers)
        
    # Freemium Preview Protocol
    return JSONResponse(content={
        "status": "sample_preview",
        "total_records_available": len(CATALOGS[dataset_name]),
        "sample_data": CATALOGS[dataset_name][:2],
        "unlock_instructions": {
            "full_endpoint": f"https://x402-agent-tollbooth.onrender.com/v1/schema/{dataset_name}.json?full=true",
            "cost": "1.00 USDC",
            "network": "Base (ChainID 8453)",
            "token_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "recipient": WALLET_ADDRESS,
            "protocol": "Send 1.00 USDC on Base, retry with header: X-PAYMENT: <tx_hash>"
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("tollbooth_agent:app", host="0.0.0.0", port=port)
