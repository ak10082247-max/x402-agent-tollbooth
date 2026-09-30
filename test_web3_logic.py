import requests

BASE_URL = "http://localhost:8000"
ENDPOINT = f"{BASE_URL}/v1/schema/deprecation_fixes_2026.json"

print("Running Test A (The Challenge): Send request with no header...")
response = requests.get(ENDPOINT)
print(f"Status Code: {response.status_code}")
print("Headers contains x-402-payment-required:", "x-402-payment-required" in response.headers)
print(f"Response Body: {response.text}")
print("-" * 50)

print("Running Test B (The Fake Payment): Send request with X-PAYMENT: 0xfake_transaction_hash...")
headers = {"X-PAYMENT": "0xfake_transaction_hash"}
response = requests.get(ENDPOINT, headers=headers)
print(f"Status Code: {response.status_code}")
print(f"Response Body: {response.text}")
print("-" * 50)
