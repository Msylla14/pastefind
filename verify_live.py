import requests
import json
import time

API_URL = "https://pastefind.onrender.com/api/analyze"
TEST_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ" # Rick Roll - Standard Test

def test_live_api():
    print("Testing LIVE API at:", API_URL)
    print("Target Video:", TEST_URL)
    
    start_time = time.time()
    try:
        response = requests.post(API_URL, json={"url": TEST_URL}, timeout=60)
        duration = time.time() - start_time
        
        print(f"Response time: {duration:.2f}s")
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                 print("API returned error logic:", data['error'])
            else:
                 print("SUCCESS! Recognition working.")
                 print("Title:", data.get('title'))
                 print("Artist:", data.get('subtitle'))
        else:
            print("HTTP Error:", response.text)
            
    except Exception as e:
        print(f"Connection Failed: {e}")

if __name__ == "__main__":
    test_live_api()
