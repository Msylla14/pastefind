import asyncio
import os
from main import identify_song, VideoURL

# Test URL (Justin Bieber - Sorry) - usually easy to identify
TEST_URL = "https://www.youtube.com/watch?v=fRh_vgS2dFE"
# Or a TikTok link if available, but let's start with YT.

async def test():
    print(f"Testing URL: {TEST_URL}")
    data = VideoURL(url=TEST_URL)
    try:
        result = await identify_song(data)
        print("Result:", result)
    except Exception as e:
        print("Error encountered:", e)

if __name__ == "__main__":
    asyncio.run(test())
