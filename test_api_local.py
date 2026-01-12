import requests
import json
import time

API_URL = "http://127.0.0.1:8000/api/analyze"
TEST_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ" # Rick Roll - reliable test

def test_api():
    print(f"Testing API at {API_URL} with {TEST_URL}...")
    try:
        response = requests.post(API_URL, json={"url": TEST_URL})
        print(f"Status Code: {response.status_code}")
        print("Response Body:")
        try:
            print(json.dumps(response.json(), indent=2))
        except:
            print(response.text)
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    # Wait a bit for server to possibly start if run in parallel (manual check required first)
    test_api()
