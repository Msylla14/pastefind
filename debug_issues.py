import yt_dlp
import asyncio
from shazamio import Shazam
import os
import uuid
import logging
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_analysis(url, label):
    print(f"\n--- Testing {label}: {url} ---")
    
    unique_id = str(uuid.uuid4())
    base_filename = f"debug_{unique_id}"
    output_template = f"{base_filename}.%(ext)s"
    final_filename = f"{base_filename}.mp3"
    
    # Base options
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'quiet': False, # Verbose for debug
        'no_warnings': False,
        'noplaylist': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    # Domain-specific configuration
    if "youtube.com" in url or "youtu.be" in url:
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['ios']
            }
        }
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
    else:
        # Facebook/Others - Desktop UA
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.google.com/',
        }

    try:
        # 1. Download
        print(f"Downloading...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        if not os.path.exists(final_filename):
            print("Download failed: File not found.")
            return

        print("Download successful.")

        # 2. Analyze
        print("Analyzing with Shazam...")
        shazam = Shazam()
        out = await shazam.recognize(final_filename)
        
        # Dump RAW JSON to inspect structure
        print("--- RAW SHAZAM RESPONSE ---")
        print(json.dumps(out, indent=2))
        print("---------------------------")
        
        # Cleanup
        os.remove(final_filename)

    except Exception as e:
        print(f"Error: {e}")

async def main():
    # Facebook Reel from screenshot
    fb_url = "https://www.facebook.com/reel/1253145953287220/"
    await test_analysis(fb_url, "Facebook Reel")

    # YouTube Short from screenshot (approximate ID from what I can read)
    # The screenshot shows https://youtube.com/shorts/8FyQ8qqQikcY...
    yt_url = "https://youtube.com/shorts/8FyQ8qqQikcY"
    await test_analysis(yt_url, "YouTube Short")

if __name__ == "__main__":
    asyncio.run(main())
