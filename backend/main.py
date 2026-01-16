from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from acrcloud.recognizer import ACRCloudRecognizer
import yt_dlp
import asyncio
import logging
import os
import uuid
import json
import urllib.parse

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ACRCloud Configuration
ACRCLOUD_CONFIG = {
    'host': os.getenv('ACRCLOUD_HOST', 'identify-eu-west-1.acrcloud.com'),
    'access_key': os.getenv('ACRCLOUD_ACCESS_KEY', ''),
    'access_secret': os.getenv('ACRCLOUD_SECRET_KEY', ''),
    'timeout': 30
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
            return {"error": f"Aucune correspondance trouvée ({msg})"}

        metadata = result.get('metadata', {})
        music_list = metadata.get('music', [])
        
        if not music_list:
            return {"error": "Aucune musique identifiée dans l'audio."}

        # Take first result
        music = music_list[0]
        title = music.get('title', 'Unknown Title')
        
        # Artists
        artists = music.get('artists', [])
        artist_names = [a.get('name') for a in artists]
        subtitle = ", ".join(artist_names) if artist_names else "Unknown Artist"
        
        # Album / Cover
        album = music.get('album', {})
        image = album.get('cover', '')
        
        # External Metadata
        external = music.get('external_metadata', {})
        spotify_data = external.get('spotify', {})
        youtube_data = external.get('youtube', {})
        
        spotify_url = ""
        youtube_url = ""
        apple_music_url = "" 

        # Spotify
        if isinstance(spotify_data, dict):
            if 'track' in spotify_data:
                track_id = spotify_data['track'].get('id')
                if track_id:
                    spotify_url = f"https://open.spotify.com/track/{track_id}"
        
        # YouTube
        if isinstance(youtube_data, dict):
            vid = youtube_data.get('vid')
            if vid:
                youtube_url = f"https://www.youtube.com/watch?v={vid}"

        # --- FALLBACKS: Generate Search Links if direct links missing ---
        if not spotify_url and title:
            query = urllib.parse.quote(f"{title} {subtitle}")
            spotify_url = f"https://open.spotify.com/search/{query}"
            
        if not youtube_url and title:
            query = urllib.parse.quote(f"{title} {subtitle}")
            youtube_url = f"https://www.youtube.com/results?search_query={query}"

        return {
            "title": title,
            "subtitle": subtitle,
            "image": image,
            "spotify_url": spotify_url,
            "youtube_url": youtube_url,
            "apple_music": apple_music_url 
        }

    except Exception as e:
        logger.error(f"ACRCloud Error: {e}")
        return {"error": str(e)}

def download_audio(url: str):
    """
    Downloads audio using yt-dlp with anti-detection features to bypass YouTube blocking.
    Returns the absolute path to the downloaded mp3 file or None if failed.
    """
    # Use cross-platform temp directory
    temp_dir = "/tmp" if os.path.exists("/tmp") else os.path.dirname(os.path.abspath(__file__))
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': f'{temp_dir}/%(id)s.%(ext)s',
        'quiet': False,
        'no_warnings': False,
        'extract_flat': False,
        'postprocessor_args': [
            '-t', '60'
        ],
        
        # Anti-detection YouTube
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'nocheckcertificate': True,
        'age_limit': None,
        'geo_bypass': True,
        'socket_timeout': 60,
        
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            final_filename = os.path.splitext(filename)[0] + ".mp3"
            return final_filename
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Erreur yt-dlp: {error_msg}")
        
        if 'HTTP Error 403' in error_msg or 'Sign in' in error_msg:
            logger.error("YouTube a bloqué le téléchargement (bot détecté)")
            return None
        elif 'Video unavailable' in error_msg:
            logger.error("Vidéo indisponible (privée/supprimée/géo-restreinte)")
            return None
        else:
            logger.error(f"Erreur inconnue: {error_msg}")
            return None

async def process_url_analysis(data: VideoURL):
    url = data.url
    logger.info(f"📥 Début téléchargement: {url}")
    
    # Run download in executor
    audio_file = await asyncio.get_event_loop().run_in_executor(None, download_audio, url)

    if not audio_file:
        logger.error("❌ Téléchargement échoué")
        return {'error': 'Impossible de télécharger l\'audio (YouTube block/Error)'}

    logger.info(f"✅ Audio téléchargé: {audio_file}")
    logger.info(f"🎵 Envoi à ACRCloud...")

    try:
        # Run ACRCloud analysis in executor
        result = await asyncio.get_event_loop().run_in_executor(None, analyze_audio_with_acrcloud, audio_file)
        logger.info(f"📊 Résultat ACRCloud: {result}")
        
        # Fallback for youtube_url if ACRCloud didn't find one but source is YT
        if "error" not in result and not result.get("youtube_url") and ("youtube.com" in url or "youtu.be" in url):
            result["youtube_url"] = url
            
        return result
    finally:
        # Cleanup
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
                logger.info(f"🗑️ Fichier temporaire supprimé: {audio_file}")
            except Exception as e:
                logger.warning(f"Failed to delete {audio_file}: {e}")

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

@app.get("/health")
async def health_check():
    configured = bool(ACRCLOUD_CONFIG['access_key'])
    return {"status": "healthy", "service": "PasteFind API (ACRCloud)", "acr_configured": configured}
