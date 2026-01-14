import requests

def check_headers():
    url = "https://pastefind.com"
    print(f"Checking headers for {url}...")
    try:
        r = requests.get(url)
        print("Status:", r.status_code)
        print("Server:", r.headers.get("Server", "Unknown"))
        print("Content-Type:", r.headers.get("Content-Type", "Unknown"))
        print("\nHeaders:")
        for k, v in r.headers.items():
            print(f"{k}: {v}")
    except Exception as e:
        print(e)

if __name__ == "__main__":
    check_headers()
