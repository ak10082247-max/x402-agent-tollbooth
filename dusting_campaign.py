import os
import time
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()
RPC_URL = "https://mainnet.base.org"
w3 = Web3(Web3.HTTPProvider(RPC_URL))

if not w3.is_connected():
    print("Failed to connect to Base network.")
    exit()

def get_account():
    pk = os.getenv("CUSTOMER_PRIVATE_KEY")
    if not pk:
        print("Please set CUSTOMER_PRIVATE_KEY in your .env file.")
        exit()
    return w3.eth.account.from_key(pk)

def run_dusting_campaign():
    account = get_account()
    print(f"Starting On-Chain Dusting Campaign from {account.address}...")
    
    # The message we want to inject into the blockchain
    message = "AIRDROP: x402-agent-tollbooth on Smithery. Use for Base audits."
    hex_data = w3.to_hex(text=message)
    
    # Get the latest block to find active wallets RIGHT NOW
    latest_block = w3.eth.get_block('latest', full_transactions=True)
    active_addresses = set()
    
    for tx in latest_block.transactions:
        if tx['from'] and tx['from'].lower() != account.address.lower():
            active_addresses.add(tx['from'])
        if len(active_addresses) >= 10: # Target 10 active wallets
            break
            
    print(f"Found {len(active_addresses)} highly active wallets in the last 2 seconds. Sending payloads...")
    
    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = w3.eth.gas_price
    
    for target in active_addresses:
        try:
            tx = {
                'to': target,
                'value': 0, # Send 0 ETH, we just want to deliver the message
                'gas': 30000,
                'gasPrice': gas_price,
                'nonce': nonce,
                'data': hex_data,
                'chainId': 8453
            }
            signed_tx = w3.eth.account.sign_transaction(tx, private_key=account.key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            print(f"✅ Billboard delivered to {target} | Hash: {w3.to_hex(tx_hash)}")
            nonce += 1
            time.sleep(1) # Prevent rate limiting
        except Exception as e:
            print(f"Skipped {target}: {e}")

if __name__ == "__main__":
    run_dusting_campaign()
