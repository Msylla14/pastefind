import requests
import json
import sys

BASE_URL = "https://pastefind.onrender.com"
ENDPOINTS = [
    "/",
    "/docs",
    "/health"
]

def check_endpoints():
    print("--- 1 Checking Endpoints ---")
    for endpoint in ENDPOINTS:
        url = BASE_URL + endpoint
        try:
            response = requests.get(url, timeout=10)
            print(f"[{response.status_code}] {url}")
        except Exception as e:
            print(f"[ERROR] {url}: {e}")

def check_analyze():
    print("\n--- 3 Testing /api/analyze ---")
    url = f"{BASE_URL}/api/analyze"
    payload = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        print(f"Status Code: {response.status_code}")
        print("Response Body:")
        try:
            print(json.dumps(response.json(), indent=2))
        except:
            print(response.text[:500])
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    check_endpoints()
    check_analyze()
