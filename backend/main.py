from fastapi import FastAPI, Request, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from acrcloud.recognizer import ACRCloudRecognizer
import yt_dlp
import asyncio
import logging
import shutil
import os
import uuid
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ACRCloud Configuration
ACRCLOUD_CONFIG = {
    'host': os.getenv('ACRCLOUD_HOST', 'identify-eu-west-1.acrcloud.com'),
    'access_key': os.getenv('ACRCLOUD_ACCESS_KEY', ''),
    'access_secret': os.getenv('ACRCLOUD_SECRET_KEY', ''),
    'timeout': 10
}

# Mount public directory
if os.path.exists("public"):
    app.mount("/public", StaticFiles(directory="public"), name="public")
elif os.path.exists("../public"):
    app.mount("/public", StaticFiles(directory="../public"), name="public")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

class VideoURL(BaseModel):
    url: str

# --- Helper Functions ---

def analyze_audio_with_acrcloud(file_path: str):
    """
    Analyzes audio using ACRCloud SDK (Synchronous)
    """
    try:
        if not ACRCLOUD_CONFIG['access_key'] or not ACRCLOUD_CONFIG['access_secret']:
             return {"error": "Server misconfiguration: Missing API Keys"}

        recognizer = ACRCloudRecognizer(ACRCLOUD_CONFIG)
        logger.info(f"Sending to ACRCloud: {file_path}")
        
        # recognize_by_file returns a JSON string
        raw_result = recognizer.recognize_by_file(file_path, 0)
        result = json.loads(raw_result)
        
        status = result.get('status', {})
        if status.get('code') != 0:
            msg = status.get('msg', 'Unknown error')
            logger.warning(f"ACRCloud No Match/Error: {msg}")
            return {"error": f"No match found ({msg})"}

        metadata = result.get('metadata', {})
        music_list = metadata.get('music', [])
        
        if not music_list:
            return {"error": "No music identified in the audio."}

        # Take first result
        music = music_list[0]
        title = music.get('title', 'Unknown Title')
        
        # Artists
        artists = music.get('artists', [])
        artist_names = [a.get('name') for a in artists]
        subtitle = ", ".join(artist_names) if artist_names else "Unknown Artist"
        
        # Album / Cover
        album = music.get('album', {})
        # ACRCloud doesn't always give high res covers in 'album'.
        # We might need to check external_metadata or metadata.
        # But 'music.get("album", {}).get("cover")' is standard for basic tier.
        image = album.get('cover', '')
        
        # External Metadata
        external = music.get('external_metadata', {})
        spotify_data = external.get('spotify', {})
        youtube_data = external.get('youtube', {})
        
        spotify_url = ""
        youtube_url = ""
        apple_music_url = "" # ACRCloud doesn't standardized Apple Music in 'external_metadata' often, but let's check.

        # Spotify
        if isinstance(spotify_data, dict):
            # sometimes it's 'track': { 'id': ... }
            if 'track' in spotify_data:
                track_id = spotify_data['track'].get('id')
                if track_id:
                    spotify_url = f"https://open.spotify.com/track/{track_id}"
        
        # YouTube
        if isinstance(youtube_data, dict):
            vid = youtube_data.get('vid')
            if vid:
                youtube_url = f"https://www.youtube.com/watch?v={vid}"

        return {
            "title": title,
            "subtitle": subtitle,
            "image": image,
            "spotify_url": spotify_url,
            "youtube_url": youtube_url,
            "apple_music": apple_music_url # Usually empty for ACRCloud unless configured
        }

    except Exception as e:
        logger.error(f"ACRCloud Error: {e}")
        return {"error": str(e)}

async def process_url_analysis(data: VideoURL):
    url = data.url
    logger.info(f"Analyzing URL: {url}")
    
    unique_id = str(uuid.uuid4())
    base_filename = f"temp_url_{unique_id}"
    output_template = f"{base_filename}.%(ext)s"
    final_filename = f"{base_filename}.mp3"
    
    # Base options
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
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
                'player_client': ['android', 'web']
            }
        }
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
    else:
        # Facebook/Desktop
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.google.com/',
        }

    try:
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"yt-dlp download failed: {e}")
            return {"error": "Could not download audio. The link might be invalid or protected."}
        
        if not os.path.exists(final_filename):
             logger.error(f"Expected file {final_filename} not found.")
             return {"error": "Audio extraction failed."}

        # Analyze (Run synchronous ACRCloud in executor)
        result = await loop.run_in_executor(None, analyze_audio_with_acrcloud, final_filename)
        
        # Fallback for youtube_url if ACRCloud didn't find one but source is YT
        if not result.get("youtube_url") and ("youtube.com" in url or "youtu.be" in url):
            result["youtube_url"] = url
            
        return result

    except Exception as e:
        logger.error(f"URL Analysis Error: {e}")
        return {"error": f"Internal Error: {str(e)}"}
    
    finally:
        if os.path.exists(final_filename):
            try:
                os.remove(final_filename)
            except:
                pass

async def process_file_analysis(file: UploadFile):
    unique_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1] or ".tmp"
    temp_filename = f"temp_file_{unique_id}{ext}"
    
    try:
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, analyze_audio_with_acrcloud, temp_filename)
        return result

    except Exception as e:
        logger.error(f"File Analysis Error: {e}")
        return {"error": f"File processing failed: {str(e)}"}
    
    finally:
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except:
                 pass

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/analyze")
async def analyze_route(video: VideoURL):
    result = await process_url_analysis(video)
    if not result:
         raise HTTPException(status_code=400, detail="Analysis failed")
    if "error" in result:
         return JSONResponse(content=result) # Return error as JSON, not 500
    return JSONResponse(content=result)

@app.post("/api/analyze-file")
async def analyze_file_route(file: UploadFile = File(...)):
    result = await process_file_analysis(file)
    if not result:
         raise HTTPException(status_code=400, detail="Analysis failed")
    if "error" in result:
         return JSONResponse(content=result)
    return JSONResponse(content=result)

@app.get("/health")
async def health_check():
    configured = bool(ACRCLOUD_CONFIG['access_key'])
    return {"status": "healthy", "service": "PasteFind API (ACRCloud)", "acr_configured": configured}
