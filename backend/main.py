from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import yt_dlp
import asyncio
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production: ["https://pastefind.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

class VideoURL(BaseModel):
    url: str

async def identify_song(data: VideoURL):
    url = data.url
    logger.info(f"Analyzing URL: {url}")
    
    # Enhanced yt-dlp options
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'bestaudio/best',
        'noplaylist': True,
        'extract_flat': 'in_playlist', # Extract metadata efficiently, avoid full download parsing if possible
        'geo_bypass': True,
        'nocheckcertificate': True,
        'ignoreerrors': True, # Don't crash on individual errors
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    }

    try:
        # Run yt-dlp in executor
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False))
        
        if not info:
             logger.error("No info returned from yt-dlp")
             return None

        # Handle 'flat' extraction where info might be entries list
        if 'entries' in info:
             # It's a playlist or flat extraction, take first entry
             if len(info['entries']) > 0:
                 info = info['entries'][0]
        
        # Extract metadata safe defaults
        title = info.get('title', 'Unknown Title')
        uploader = info.get('uploader', 'Unknown Artist')
        thumbnail = info.get('thumbnail', '')
        webpage_url = info.get('webpage_url', url)
        
        # Detect if it looks like an error
        if not title and not uploader:
             logger.warning("Extracted info has no title or uploader")
             return {"error": "Could not extract metadata"}

        logger.info(f"Successfully analyzed: {title}")
        return {
            "title": title,
            "subtitle": uploader,
            "image": thumbnail,
            "apple_music": "",
            "spotify_url": "",
            "youtube_url": webpage_url
        }
    except Exception as e:
        logger.error(f"Error during analysis: {e}")
        return {"error": str(e)}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/analyze")
async def analyze_route(video: VideoURL):
    result = await identify_song(video)
    
    if not result:
         # Internal error or yt-dlp returned nothing
         raise HTTPException(status_code=400, detail="Analysis failed: No result")
    
    if "error" in result:
         # Propagate the specific error message to frontend
         # We return 200 OK because we want to pass the JSON body with error details
         # OR we can return 422/400. Let's return 200 with error field so frontend logic handles it
         return JSONResponse(content={"error": result["error"], "title": "", "subtitle": ""})

    return JSONResponse(content=result)
