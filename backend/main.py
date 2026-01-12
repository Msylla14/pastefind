from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import yt_dlp
import asyncio

app = FastAPI()

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for now, or specify ["https://pastefind.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

class VideoURL(BaseModel):
    url: str

async def identify_song(data: VideoURL):
    url = data.url
    print(f"Analyzing URL: {url}")
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'bestaudio/best',
        'noplaylist': True,
        # 'extract_flat': True, # Uncomment if we only want metadata without download intent
    }

    try:
        # Run yt-dlp in a separate thread to not block async event loop
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False))
        
        # Extract metadata
        title = info.get('title', 'Unknown Title')
        uploader = info.get('uploader', 'Unknown Artist')
        thumbnail = info.get('thumbnail', '')
        webpage_url = info.get('webpage_url', url)
        
        return {
            "title": title,
            "subtitle": uploader,
            "image": thumbnail,
            "apple_music": "", # Placeholder
            "spotify_url": "", # Placeholder
            "youtube_url": webpage_url
        }
    except Exception as e:
        print(f"Error during analysis: {e}")
        return {
            "title": "Error or Invalid Link",
            "subtitle": "Could not analyze",
            "image": "",
            "youtube_url": url
        }

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/analyze")
async def analyze_route(video: VideoURL):
    result = await identify_song(video)
    if not result:
         raise HTTPException(status_code=400, detail="Analysis failed")
    return JSONResponse(content=result)
