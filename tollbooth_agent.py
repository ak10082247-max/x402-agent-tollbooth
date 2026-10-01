import os
import json
import sqlite3
import uvicorn
import httpx
from google import genai
from typing import Optional
from fastapi import FastAPI, Request
from web3 import Web3

from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

USDC_CONTRACT_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WALLET_ADDRESS = "0x73279fa4BadA7CAC888c62CDa4f5c8104765f6f1"
EXPECTED_AMOUNT = 1000000  # 1.00 USDC, 6 decimals
TRANSFER_EVENT_SIGNATURE = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Initialize Gemini client
gemini_api_key = os.environ.get("GEMINI_API_KEY")
ai_client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None

app = FastAPI(
    title="x402 Agent Tollbooth - API Fix Engine & Smart Contract Auditor",
    version="2.1.0",
    description="Live Smart Contract AI Auditor. Analyzes Base contracts for vulnerabilities. Requires 1.00 USDC payment via x402 protocol."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))

def init_db():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS payments (tx_hash TEXT PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

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

async def fetch_contract_code(address: str):
    url = f"https://api.basescan.org/api?module=contract&action=getsourcecode&address={address}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "1" and data.get("result"):
                return data["result"][0]
    return None

# MCP Server Handlers

async def list_tools_handler(ctx, params, **kwargs) -> list[types.Tool]:
    return [
        types.Tool(
            name="audit_contract",
            description="Live Smart Contract AI Auditor. Analyzes Base contracts for vulnerabilities. Requires 1.00 USDC payment via x402 protocol.",
            inputSchema={
                "type": "object",
                "properties": {
                    "contract_address": {"type": "string"},
                    "payment_hash": {"type": "string"}
                },
                "required": ["contract_address"]
            }
        )
    ]

async def call_tool_handler(ctx, params, **kwargs) -> list[types.TextContent]:
    name = params.name
    arguments = params.arguments

    if name != "audit_contract":
        raise ValueError(f"Unknown tool: {name}")

    address = arguments.get("contract_address")
    receipt_hash = arguments.get("payment_hash")

    if not receipt_hash:
        contract_data = await fetch_contract_code(address)
        contract_name = contract_data.get("ContractName", "Unknown") if contract_data else "Unknown"
        compiler = contract_data.get("CompilerVersion", "Unknown") if contract_data else "Unknown"
        result = {
            "error": "Payment Required",
            "contract_name": contract_name,
            "compiler_version": compiler,
            "status": "Deep AI Vulnerability Audit locked. Pay 1.00 USDC on Base to 0x73279fa4BadA7CAC888c62CDa4f5c8104765f6f1 to unlock.",
            "unlock_instructions": {
                "cost": "1.00 USDC",
                "network": "Base (ChainID 8453)",
                "token_contract": USDC_CONTRACT_ADDRESS,
                "recipient": WALLET_ADDRESS,
                "protocol": "Send 1.00 USDC on Base, retry with parameter: payment_hash: <tx_hash>"
            }
        }
        return [types.TextContent(type="text", text=json.dumps(result))]

    status = verify_payment(receipt_hash)
    if status == "ALREADY_REDEEMED":
        return [types.TextContent(type="text", text=json.dumps({"error": "Transaction hash already redeemed"}))]
    elif status == True:
        contract_data = await fetch_contract_code(address)
        if not contract_data or not contract_data.get("SourceCode"):
            return [types.TextContent(type="text", text=json.dumps({"error": "Contract source code not found or not verified on BaseScan."}))]
        
        source_code = contract_data["SourceCode"]
        if ai_client:
            prompt = f"Analyze this Solidity smart contract for honeypots, mint privileges, or rug-pull vulnerabilities. Return a strict JSON risk profile.\\n\\nContract Code:\\n{source_code[:30000]}"
            try:
                ai_response = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        response_mime_type="application/json",
                    )
                )
                return [types.TextContent(type="text", text=ai_response.text)]
            except Exception as e:
                return [types.TextContent(type="text", text=json.dumps({"error": f"AI analysis failed: {str(e)}"}))]
        else:
            return [types.TextContent(type="text", text=json.dumps({"error": "Gemini API key not configured."}))]
    else:
        return [types.TextContent(type="text", text=json.dumps({"error": "Invalid or missing payment transfer"}))]

server = Server("x402-auditor", on_list_tools=list_tools_handler, on_call_tool=call_tool_handler)
sse = SseServerTransport("/messages/")

async def handle_sse(request):
    if request.method == "POST":
        try:
            body = await request.json()
            method = body.get("method")
            msg_id = body.get("id")
            if method == "initialize":
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "x402-auditor", "version": "1.0.0"}
                    }
                })
            elif method == "tools/list":
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": [{
                            "name": "audit_contract",
                            "description": "Live Smart Contract AI Auditor. Analyzes Base contracts for vulnerabilities. Requires 1.00 USDC payment via x402 protocol.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "contract_address": {"type": "string", "description": "The Base contract address to audit"},
                                    "user_wallet": {"type": "string", "description": "The wallet address making the request"}
                                },
                                "required": ["contract_address", "user_wallet"]
                            }
                        }]
                    }
                })
            elif method in ["resources/list", "prompts/list"]:
                key = "resources" if "resources" in method else "prompts"
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {key: []}
                })
            else:
                return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}})
        except Exception:
            return JSONResponse({"error": "Bad Request"}, status_code=400)
    
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())

async def handle_messages(request):
    await sse.handle_post_message(request.scope, request.receive, request._send)

async def server_card_handler(request):
    if request.method == "POST":
        return JSONResponse({"error": "Standard HTTP POST not supported. Please use SSE or fetch server-card.json"}, status_code=400)
    return JSONResponse({
        "serverInfo": {"name": "x402-auditor", "version": "1.0.0"},
        "tools": [{"name": "audit_contract", "description": "Live Smart Contract AI Auditor. Analyzes Base contracts for vulnerabilities. Requires 1.00 USDC payment via x402 protocol."}]
    })

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

mcp_app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET", "POST", "OPTIONS"]),
        Route("/messages/", endpoint=handle_messages, methods=["POST", "OPTIONS"]),
        Route("/{path:path}", endpoint=server_card_handler, methods=["GET", "POST", "OPTIONS"])
    ],
    middleware=[
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    ]
)

app.mount("/", mcp_app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("tollbooth_agent:app", host="0.0.0.0", port=port)
