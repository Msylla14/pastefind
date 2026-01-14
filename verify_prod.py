import requests
import json

API_URL = "https://pastefind.com/api/analyze"
TEST_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ" # Rick Roll

def test_prod():
    print(f"Testing PROD API at {API_URL}...")
    try:
        response = requests.post(API_URL, json={"url": TEST_URL}, timeout=30)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
             print("SUCCESS: Production API is reachable and responding.")
             try:
                 print(json.dumps(response.json(), indent=2))
             except:
                 print("Response is not JSON:", response.text[:200])
        else:
             print(f"FAILURE: Status {response.status_code}")
             print(response.text[:200])
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_prod()
