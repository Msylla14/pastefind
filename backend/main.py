from fastapi import FastAPI, Request, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import yt_dlp
import asyncio
import logging
import shutil
from shazamio import Shazam
import os
import uuid

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Mount public directory for static assets (bg image)
if os.path.exists("public"):
    app.mount("/public", StaticFiles(directory="public"), name="public")
elif os.path.exists("../public"):
    # Fallback if run from backend directory
    app.mount("/public", StaticFiles(directory="../public"), name="public")

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

# --- Helper Functions ---

async def analyze_audio_content(file_path: str, source_url: str = ""):
    """
    Analyzes an audio file using Shazam and formats the response.
    """
    try:
        shazam = Shazam()
        try:
            out = await shazam.recognize(file_path)
        except Exception as e:
            logger.error(f"Shazam recognition failed: {e}")
            return {"error": "Music recognition service unavailable."}
        
    # Parse Result
        track = out.get('track', {})
        if not track:
             return {"error": "No music recognized."}

        title = track.get('title', 'Unknown Title')
        subtitle = track.get('subtitle', 'Unknown Artist')
        images = track.get('images', {})
        cover_art = images.get('coverarthq', images.get('coverart', images.get('background', '')))
        
        # Links - Parse Hub Actions & Providers
        hub = track.get('hub', {})
        
        # Initialize links
        spotify_url = ""
        youtube_url = ""
        apple_music_url = ""

        # 1. Check top-level actions (often Apple Music)
        actions = hub.get('actions', [])
        for action in actions:
            if action.get('type') == 'uri':
                 uri = action.get('uri', '')
                 if "apple" in uri or "itunes" in uri:
                     apple_music_url = uri

        # 2. Check Providers (Spotify, YouTube Music, etc.)
        providers = hub.get('providers', [])
        for provider in providers:
            p_type = provider.get('type', '').upper()
            p_actions = provider.get('actions', [])
            for action in p_actions:
                uri = action.get('uri', '')
                if p_type == 'SPOTIFY':
                    if 'spotify:search:' in uri:
                        query = uri.split(':')[-1]
                        spotify_url = f"https://open.spotify.com/search/{query}"
                    elif 'spotify:track:' in uri:
                        track_id = uri.split(':')[-1]
                        spotify_url = f"https://open.spotify.com/track/{track_id}"
                elif p_type == 'YOUTUBEMUSIC' and not youtube_url:
                     youtube_url = uri
        
        # 3. Check Sections for official Video
        sections = track.get('sections', [])
        for section in sections:
             if section.get('type') == 'VIDEO':
                  yt_vid_url = section.get('youtubeurl', '')
                  if yt_vid_url:
                      youtube_url = yt_vid_url
                      break
        
        if not youtube_url and source_url:
             # Only fallback to source if it looks like a music video platform, otherwise empty?
             # User requested "option vers les son origine". If we don't have a YouTube link found, 
             # returning the source (Facebook info) is less useful than specific YouTube search/video.
             # But let's keep source_url as last resort fallback for "YouTube" button if source WAS youtube.
             if "youtube" in source_url or "youtu.be" in source_url:
                youtube_url = source_url

        logger.info(f"Successfully analyzed: {title} by {subtitle}")
        return {
            "title": title,
            "subtitle": subtitle,
            "image": cover_art,
            "apple_music": apple_music_url,            
            "spotify_url": spotify_url,
            "youtube_url": youtube_url
        }
    except Exception as e:
        logger.error(f"Error parsing Shazam result: {e}")
        return {"error": f"Analysis failed: {str(e)}"}

# --- Core Logic ---

async def process_url_analysis(data: VideoURL):
    url = data.url
    logger.info(f"Analyzing URL: {url}")
    
    unique_id = str(uuid.uuid4())
    base_filename = f"temp_url_{unique_id}"
    output_template = f"{base_filename}.%(ext)s"
    final_filename = f"{base_filename}.mp3"
    
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
        # YouTube Shorts often require Android client emulation
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
        # Facebook/TikTok/Others often prefer Desktop UA
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
            return {"error": "Could not download audio. The link might be invalid, private, or blocked."}
        
        if not os.path.exists(final_filename):
             logger.error(f"Expected file {final_filename} not found after download.")
             return {"error": "Audio extraction failed."}

        # Analyze
        result = await analyze_audio_content(final_filename, source_url=url)
        return result

    except Exception as e:
        logger.error(f"Unexpected error during URL analysis: {e}")
        return {"error": f"An internal error occurred: {str(e)}"}
    
    finally:
        if os.path.exists(final_filename):
            try:
                os.remove(final_filename)
                logger.info(f"Deleted temp file: {final_filename}")
            except Exception as e:
                logger.warning(f"Failed to delete {final_filename}: {e}")

async def process_file_analysis(file: UploadFile):
    unique_id = str(uuid.uuid4())
    # Preserve extension or convert? Shazam handles many formats. 
    # But safe to assume we just save it as is.
    ext = os.path.splitext(file.filename)[1]
    if not ext:
        ext = ".tmp"
    
    temp_filename = f"temp_file_{unique_id}{ext}"
    
    try:
        # Save uploaded file
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"Saved uploaded file to {temp_filename}")
        
        # Analyze
        result = await analyze_audio_content(temp_filename)
        return result

    except Exception as e:
        logger.error(f"Error processing file upload: {e}")
        return {"error": f"File processing failed: {str(e)}"}
    
    finally:
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
                logger.info(f"Deleted temp file: {temp_filename}")
            except Exception as e:
                logger.warning(f"Failed to delete {temp_filename}: {e}")

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/analyze")
async def analyze_route(video: VideoURL):
    result = await process_url_analysis(video)
    
    if not result:
         raise HTTPException(status_code=400, detail="Analysis failed: No result")
    
    if "error" in result:
         return JSONResponse(content={"error": result["error"], "title": "", "subtitle": ""})

    return JSONResponse(content=result)

@app.post("/api/analyze-file")
async def analyze_file_route(file: UploadFile = File(...)):
    # Validate file size
    logger.info(f"Receiving file upload: {file.filename}")
    result = await process_file_analysis(file)
    
    if not result:
         raise HTTPException(status_code=400, detail="Analysis failed: No result")

    if "error" in result:
         return JSONResponse(content={"error": result["error"], "title": "", "subtitle": ""})

    return JSONResponse(content=result)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "PasteFind API"}
