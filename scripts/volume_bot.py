import os
import time
import random
import json
from web3 import Web3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
RPC_URL = "https://mainnet.base.org"
TOLLBOOTH_WALLET = "0x73279fa4BadA7CAC888c62CDa4f5c8104765f6f1"
USDC_CONTRACT_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Setup Web3
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    print("Failed to connect to Base network.")
    exit()

# ERC20 ABI (Only Transfer needed)
ERC20_ABI = json.loads('[{"constant":false,"inputs":[{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transfer","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"}]')

def get_account():
    pk = os.getenv("CUSTOMER_PRIVATE_KEY")
    if not pk:
        print("Please set CUSTOMER_PRIVATE_KEY in your .env file.")
        exit()
    return w3.eth.account.from_key(pk)

def send_usdc(amount_usdc):
    account = get_account()
    usdc_contract = w3.eth.contract(address=USDC_CONTRACT_ADDRESS, abi=ERC20_ABI)
    
    # USDC has 6 decimals
    amount_wei = int(amount_usdc * 1_000_000)
    
    print(f"Preparing to send {amount_usdc} USDC to {TOLLBOOTH_WALLET}...")
    
    # Build transaction
    tx = usdc_contract.functions.transfer(TOLLBOOTH_WALLET, amount_wei).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price
    })
    
    # Sign and send
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    
    print(f"✅ Transaction sent! Hash: {w3.to_hex(tx_hash)}")
    print(f"View on BaseScan: https://basescan.org/tx/{w3.to_hex(tx_hash)}")
    return w3.to_hex(tx_hash)

if __name__ == "__main__":
    print("🤖 Starting x402 Autonomous Volume Seeder...")
    print("This bot will periodically send micro-transactions to your tollbooth to build on-chain history.")
    
    while True:
        # We simulate buying the "memory.store" tool to keep it cheap (0.01 USDC)
        # but generate high transaction counts.
        try:
            send_usdc(0.01)
        except Exception as e:
            print(f"Error: {e}")
        
        # Sleep for a random interval between 1 and 4 hours to look organic
        sleep_time = random.randint(3600, 14400)
        print(f"Sleeping for {sleep_time / 3600:.2f} hours before the next autonomous purchase...\n")
        time.sleep(sleep_time)
