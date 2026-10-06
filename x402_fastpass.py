import asyncio
from web3 import Web3
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class X402FastPass:
    """
    Seamless Client SDK for the x402-agent-tollbooth.
    Abstracts away the crypto-payment complexity so AI Agents can seamlessly access premium MCP tools.
    """
    def __init__(self, private_key: str, rpc_url: str = "https://mainnet.base.org"):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = self.w3.eth.account.from_key(private_key)
        self.usdc_contract_address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
        self.tollbooth_wallet = "0x73279fa4BadA7CAC888c62CDa4f5c8104765f6f1"
        
        # Standard ERC-20 ABI for transfer
        self.erc20_abi = [
            {
                "constant": False,
                "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}],
                "name": "transfer",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            }
        ]
        self.usdc = self.w3.eth.contract(address=self.usdc_contract_address, abi=self.erc20_abi)

    def _pay_toll(self, amount_usdc: float) -> str:
        """Executes the USDC transfer and returns the transaction hash."""
        print(f"[X402 FastPass] Processing payment of {amount_usdc} USDC to Tollbooth...")
        amount_wei = int(amount_usdc * 10**6) # USDC has 6 decimals
        
        tx = self.usdc.functions.transfer(self.tollbooth_wallet, amount_wei).build_transaction({
            'from': self.account.address,
            'nonce': self.w3.eth.get_transaction_count(self.account.address),
            'gas': 100000,
            'gasPrice': self.w3.eth.gas_price
        })
        
        signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.account.key)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        # Wait for receipt to ensure it's mined before hitting the MCP
        self.w3.eth.wait_for_transaction_receipt(tx_hash)
        hash_hex = self.w3.to_hex(tx_hash)
        print(f"[X402 FastPass] Payment confirmed! Hash: {hash_hex}")
        return hash_hex

    async def _call_mcp_tool(self, tool_name: str, arguments: dict):
        # We assume the MCP server is installed locally or accessible via npx
        server_params = StdioServerParameters(
            command="uv",
            args=["run", "tollbooth_agent.py"],
            env=None
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                return result

    async def audit_contract(self, contract_address: str):
        """Seamless wrapper for contract.audit. Automatically pays the 1.00 USDC toll."""
        tx_hash = self._pay_toll(1.00)
        return await self._call_mcp_tool("contract.audit", {
            "contractAddress": contract_address,
            "paymentHash": tx_hash,
            "referralWallet": self.account.address # Self-referral for 20% kickback!
        })

    async def patch_contract(self, contract_address: str):
        """Seamless wrapper for contract.patch. Automatically pays the 5.00 USDC toll."""
        tx_hash = self._pay_toll(5.00)
        return await self._call_mcp_tool("contract.patch", {
            "contractAddress": contract_address,
            "paymentHash": tx_hash,
            "referralWallet": self.account.address
        })

# --- Example Usage for an AI Agent ---
if __name__ == "__main__":
    print("X402 FastPass SDK initialized.")
    # client = X402FastPass(private_key="YOUR_PRIVATE_KEY")
    # asyncio.run(client.audit_contract("0x..."))
