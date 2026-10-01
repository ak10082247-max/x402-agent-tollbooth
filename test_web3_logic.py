import requests
import json

BASE_URL = "http://localhost:8000"
ENDPOINT = f"{BASE_URL}/v1/schema/react19_nextjs_migrations.json"

print("Test 1: Sample Preview (No full param, no header)...")
r1 = requests.get(ENDPOINT)
print(f"Status Code: {r1.status_code}")
print(f"Body: {json.dumps(r1.json(), indent=2)[:300]}...\n")

print("Test 2: Challenge GET (full=true, no header)...")
r2 = requests.get(ENDPOINT + "?full=true")
print(f"Status Code: {r2.status_code}")
print(f"Headers: {r2.headers.get('x-402-payment-required')} {r2.headers.get('x-402-token')} {r2.headers.get('x-402-network')}")
print(f"Body: {r2.text}\n")

print("Test 3: Invalid Payment GET (header set, invalid hash)...")
r3 = requests.get(ENDPOINT, headers={"X-PAYMENT": "0xfake"})
print(f"Status Code: {r3.status_code}")
print(f"Body: {r3.text}\n")
