import yt_dlp
import os
import uuid

def test_download(url):
    print(f"Testing download for: {url}")
    unique_id = str(uuid.uuid4())
    base_filename = f"test_download_{unique_id}"
    output_template = f"{base_filename}.%(ext)s"
    final_filename = f"{base_filename}.mp3"

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'quiet': False, # Show output for debugging
        'no_warnings': False,
        'noplaylist': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.google.com/',
        },
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        if os.path.exists(final_filename):
            print(f"SUCCESS: File downloaded to {final_filename}")
            # Clean up
            os.remove(final_filename)
        else:
            print("FAILURE: Download finished but file not found.")
            
    except Exception as e:
        print(f"FAILURE: Exception occurred: {e}")

if __name__ == "__main__":
    # Test with a known safe YouTube video (e.g. valid music video or copyright free)
    # Using a standard music video to test extraction
    test_download("https://www.youtube.com/watch?v=dQw4w9WgXcQ") 
