import requests

URL = "https://pastefind-backend.onrender.com/"

def check_root():
    print(f"Checking {URL}...")
    try:
        r = requests.get(URL, timeout=10)
        print("Status:", r.status_code)
        print(r.text[:200])
    except Exception as e:
        print(e)

if __name__ == "__main__":
    check_root()
