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

from shazamio import Shazam
import os
import uuid

async def identify_song(data: VideoURL):
    url = data.url
    logger.info(f"Analyzing URL: {url}")
    
    unique_id = str(uuid.uuid4())
    temp_filename = f"temp_{unique_id}.mp3"
    
    # Enhanced yt-dlp options for audio download
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_filename,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    try:
        # 1. Download Audio via yt-dlp
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))
        
        # Check if file exists (yt-dlp might append .mp3)
        final_filename = temp_filename
        if not os.path.exists(final_filename):
            final_filename = temp_filename + ".mp3"
        
        if not os.path.exists(final_filename):
             logger.error("Audio download failed")
             return {"error": "Failed to download audio track"}

        # 2. Recognize with Shazam
        shazam = Shazam()
        out = await shazam.recognize(final_filename)
        
        # Cleanup temp file
        if os.path.exists(final_filename):
            os.remove(final_filename)

        # 3. Parse Result
        track = out.get('track', {})
        if not track:
             return {"error": "No music found or song not recognized"}

        title = track.get('title', 'Unknown Title')
        subtitle = track.get('subtitle', 'Unknown Artist')
        images = track.get('images', {})
        cover_art = images.get('coverarthq', images.get('background', ''))
        
        # Links
        hub = track.get('hub', {})
        actions = hub.get('actions', [])
        spotify_url = ""
        for action in actions:
            if action.get('type') == 'uri':
                 spotify_url = action.get('uri', '') # Often returns deep link, verify payload
        
        # Shazam often provides provider links in 'sections' or 'hub'. 
        # For simplicity, we use what we have or search metadata if needed.
        # shazamio often explicitly gives providers in some versions, but let's stick to basic extraction first.
        sections = track.get('sections', [])
        for section in sections:
            if section.get('type') == 'SONG':
                for metadata in section.get('metadata', []):
                     if metadata.get('title') == 'Spotify':
                          # Sometimes text is the link? vary rare.
                          pass

        # Construct reliable response
        # Note: Spotify URL might need a separate lookup if Shazam doesn't provide a direct web link (it often provides 'spotify:track:...')
        # We can construct web link if we have the ID.
        
        web_spotify_url = ""
        if "spotify:track:" in spotify_url:
             track_id = spotify_url.split(":")[-1]
             web_spotify_url = f"https://open.spotify.com/track/{track_id}"
        
        youtube_url = ""
        # Look for youtube link in sections or just use input url as fallback?
        # Ideally we want the OFFICIAL video found by Shazam.
        for section in sections:
             if section.get('type') == 'VIDEO':
                  youtube_url = section.get('youtubeurl', '')
                  break
        
        if not youtube_url:
             youtube_url = url # Fallback to source

        logger.info(f"Successfully analyzed: {title} by {subtitle}")
        return {
            "title": title,
            "subtitle": subtitle,
            "image": cover_art,
            "apple_music": "",
            "spotify_url": web_spotify_url,
            "youtube_url": youtube_url
        }

    except Exception as e:
        logger.error(f"Error during analysis: {e}")
        # Clean up if failed during processing
        if 'final_filename' in locals() and os.path.exists(final_filename):
             os.remove(final_filename)
        elif 'temp_filename' in locals() and os.path.exists(temp_filename):
             try:
                os.remove(temp_filename)
             except:
                pass
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
