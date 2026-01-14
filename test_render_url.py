import requests
import json

# Guessing the Render URL based on service name "pastefind-backend"
API_URL = "https://pastefind-backend.onrender.com/api/analyze"
TEST_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 

def test_render_url():
    print(f"Testing RENDER URL at {API_URL}...")
    try:
        response = requests.post(API_URL, json={"url": TEST_URL}, timeout=30)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
             print("SUCCESS: Render Backend is reachable!")
             try:
                 print(json.dumps(response.json(), indent=2))
             except:
                 print("Response is not JSON")
        else:
             print(f"FAILURE: Status {response.status_code}")
             print(response.text[:200])
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_render_url()
