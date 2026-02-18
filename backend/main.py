from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from acrcloud.recognizer import ACRCloudRecognizer
import yt_dlp
import asyncio
import logging
import os
import uuid
import json
import urllib.parse
import requests
import time

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

# AudD.io Configuration
AUDD_API_TOKEN = os.getenv('AUDD_API_TOKEN', 'test')  # 'test' token for testing, replace with real token
AUDD_API_URL = 'https://api.audd.io/'

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VideoURL(BaseModel):
    url: str

# --- Helper Functions ---

def clean_url(url: str) -> str:
    """
    Removes tracking parameters like 'fbclid', 'si', etc. from URLs.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        
        keys_to_remove = [k for k in query_params if k.startswith('fbclid') or k in ['si', 'igsh']]
        for k in keys_to_remove:
            del query_params[k]
            
        new_query = urllib.parse.urlencode(query_params, doseq=True)
        
        cleaned = urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        return cleaned
    except Exception as e:
        logger.warning(f"URL Cleaning failed: {e}")
        return url

def analyze_audio_with_audd(file_path: str):
    """
    Analyzes audio using AudD.io API (Primary service)
    Returns dict with music info or error
    """
    try:
        logger.info(f"[AudD.io] Analyzing: {file_path}")
        
        # Open file and send to AudD.io
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = {
                'api_token': AUDD_API_TOKEN,
                'return': 'apple_music,spotify,deezer'
            }
            
            response = requests.post(AUDD_API_URL, files=files, data=data, timeout=30)
            result = response.json()
        
        logger.info(f"[AudD.io] Response: {json.dumps(result, indent=2)}")
        
        # Check status
        if result.get('status') != 'success':
            error_msg = result.get('error', {}).get('error_message', 'Unknown error')
            logger.warning(f"[AudD.io] Error: {error_msg}")
            return {"error": f"AudD.io error: {error_msg}", "service": "audd"}
        
        # Check if result is null (no match)
        if result.get('result') is None:
            logger.warning(f"[AudD.io] No match found")
            return {"error": "No match found", "service": "audd"}
        
        # Extract music info
        music = result['result']
        title = music.get('title', 'Unknown Title')
        artist = music.get('artist', 'Unknown Artist')
        album = music.get('album', '')
        release_date = music.get('release_date', '')
        song_link = music.get('song_link', '')
        
        # Cover art
        image = ''
        
        # Try Spotify cover
        spotify_data = music.get('spotify', {})
        if spotify_data and 'album' in spotify_data:
            images = spotify_data['album'].get('images', [])
            if images and len(images) > 0:
                image = images[0].get('url', '')
        
        # Try Apple Music cover
        if not image:
            apple_music = music.get('apple_music', {})
            if apple_music and 'artwork' in apple_music:
                artwork_url = apple_music['artwork'].get('url', '')
                if artwork_url:
                    # Apple Music artwork URL template
                    image = artwork_url.replace('{w}', '600').replace('{h}', '600')
        
        # Try Deezer cover
        if not image:
            deezer = music.get('deezer', {})
            if deezer and 'album' in deezer:
                image = deezer['album'].get('cover_xl', '')
        
        # External links
        spotify_url = ""
        youtube_url = ""
        apple_music_url = ""
        
        # Spotify
        if spotify_data:
            external_urls = spotify_data.get('external_urls', {})
            spotify_url = external_urls.get('spotify', '')
        
        # Apple Music
        apple_music = music.get('apple_music', {})
        if apple_music:
            apple_music_url = apple_music.get('url', '')
        
        # YouTube - Generate search link
        if title and artist:
            query = urllib.parse.quote(f"{title} {artist}")
            youtube_url = f"https://www.youtube.com/results?search_query={query}"
        
        # Fallback: Generate Spotify search link if no direct link
        if not spotify_url and title:
            query = urllib.parse.quote(f"{title} {artist}")
            spotify_url = f"https://open.spotify.com/search/{query}"
        
        return {
            "title": title,
            "subtitle": artist,
            "image": image,
            "spotify_url": spotify_url,
            "youtube_url": youtube_url,
            "apple_music": apple_music_url,
            "service": "audd"
        }
        
    except requests.exceptions.Timeout:
        logger.error(f"[AudD.io] Timeout")
        return {"error": "AudD.io timeout", "service": "audd"}
    except Exception as e:
        logger.error(f"[AudD.io] Exception: {e}")
        return {"error": str(e), "service": "audd"}

def analyze_audio_with_acrcloud(file_path: str):
    """
    Analyzes audio using ACRCloud SDK (Fallback service)
    """
    try:
        logger.info(f"[ACRCloud] Analyzing: {file_path}")
        
        if not ACRCLOUD_CONFIG['access_key'] or not ACRCLOUD_CONFIG['access_secret']:
             return {"error": "ACRCloud not configured", "service": "acrcloud"}

        recognizer = ACRCloudRecognizer(ACRCLOUD_CONFIG)
        
        # recognize_by_file returns a JSON string
        raw_result = recognizer.recognize_by_file(file_path, 0)
        result = json.loads(raw_result)
        
        status = result.get('status', {})
        if status.get('code') != 0:
            msg = status.get('msg', 'Unknown error')
            logger.warning(f"[ACRCloud] No Match/Error: {msg}")
            return {"error": f"No match ({msg})", "service": "acrcloud"}

        metadata = result.get('metadata', {})
        music_list = metadata.get('music', [])
        
        if not music_list:
            return {"error": "No music identified", "service": "acrcloud"}

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
        
        # Additional fallback
        if not image:
            image = music.get('cover', '')
        
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

        # Fallbacks
        if not spotify_url and title:
            query = urllib.parse.quote(f"{title} {subtitle}")
            spotify_url = f"https://open.spotify.com/search/{query}"
            
        if not youtube_url and title:
            query = urllib.parse.quote(f"{title} {subtitle}")
            youtube_url = f"https://www.youtube.com/results?search_query={query}"

        return {
            "title": title,
            "subtitle": subtitle,
            "image": image if image else '',
            "spotify_url": spotify_url,
            "youtube_url": youtube_url,
            "apple_music": apple_music_url,
            "service": "acrcloud"
        }

    except Exception as e:
        logger.error(f"[ACRCloud] Error: {e}")
        return {"error": str(e), "service": "acrcloud"}

def analyze_audio_hybrid(file_path: str):
    """
    Hybrid system: Try AudD.io first, fallback to ACRCloud if it fails
    """
    logger.info(f"[HYBRID] Starting analysis for: {file_path}")
    
    # Try AudD.io first
    result = analyze_audio_with_audd(file_path)
    
    if "error" not in result:
        logger.info(f"[HYBRID] ✅ Success with AudD.io")
        return result
    
    logger.warning(f"[HYBRID] AudD.io failed: {result.get('error')}, trying ACRCloud...")
    
    # Fallback to ACRCloud
    result = analyze_audio_with_acrcloud(file_path)
    
    if "error" not in result:
        logger.info(f"[HYBRID] ✅ Success with ACRCloud (fallback)")
        return result
    
    logger.error(f"[HYBRID] ❌ Both services failed")
    return {"error": "Aucune correspondance trouvée (Gen Fingerprint Error (May Be Mute))"}

def download_audio(url: str):
    """
    Downloads audio using yt-dlp
    """
    temp_dir = "/tmp" if os.path.exists("/tmp") else os.path.dirname(os.path.abspath(__file__))
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '256',  # Increased from 192 to 256 for better quality
        }],
        'outtmpl': f'{temp_dir}/%(id)s.%(ext)s',
        'quiet': False,
        'no_warnings': False,
        'extract_flat': False,
        'postprocessor_args': [
            '-t', '60'
        ],
        'retries': 5,  # Increased retries for unstable connections
        'fragment_retries': 5,
        'skip_unavailable_fragments': False,
        
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': url if 'facebook.com' in url or 'instagram.com' in url else 'https://www.youtube.com/',
        'nocheckcertificate': True,
        'extractor_retries': 3,
        'fragment_retries': 3,
        'retries': 3,
        
        'http_headers': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
        }
    }
    
    # Platform-specific options
    if 'facebook.com' in url or 'fb.watch' in url or 'instagram.com' in url:
        ydl_opts['http_headers']['Referer'] = url
        ydl_opts['http_headers']['Origin'] = 'https://www.facebook.com' if 'facebook.com' in url else 'https://www.instagram.com'
        ydl_opts['http_headers']['Accept-Language'] = 'en-US,en;q=0.9'
        ydl_opts['http_headers']['Sec-Fetch-Mode'] = 'navigate'
        # Force best quality for Facebook/Instagram
        ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Downloading audio from: {url}")
            info = ydl.extract_info(url, download=True)
            
            if info is None:
                logger.error("yt-dlp returned None")
                return None
            
            video_id = info.get('id', str(uuid.uuid4()))
            mp3_path = f"{temp_dir}/{video_id}.mp3"
            
            if os.path.exists(mp3_path):
                logger.info(f"Audio downloaded: {mp3_path}")
                return mp3_path
            else:
                logger.error(f"MP3 file not found: {mp3_path}")
                return None
                
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None

# --- API Routes ---

@app.get("/")
async def root():
    return {"status": "L'API PasteFind est en cours d'exécution", "version": "2.1-hybrid", "docs_url": "/docs"}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "PasteFind API (Hybrid: AudD.io + ACRCloud)",
        "audd_configured": bool(AUDD_API_TOKEN and AUDD_API_TOKEN != 'test'),
        "acrcloud_configured": bool(ACRCLOUD_CONFIG['access_key'])
    }

@app.post("/api/analyze")
async def analyze_video(data: VideoURL):
    """
    Analyze music from a video URL (Facebook, TikTok, Instagram, etc.)
    """
    try:
        url = clean_url(data.url)
        logger.info(f"Received URL: {url}")
        
        # Block YouTube
        if 'youtube.com' in url or 'youtu.be' in url:
            return JSONResponse(
                status_code=200,
                content={
                    "error": "🚫 YouTube bloque l'extraction audio pour des raisons de droits d'auteur.\n\n💡 Solution : Téléchargez la vidéo YouTube avec une application (SnapTube, VidMate, etc.) puis utilisez le mode 'Fichier Local' pour analyser le fichier MP3/MP4."
                }
            )
        
        # Download audio
        audio_path = download_audio(url)
        
        if not audio_path:
            return JSONResponse(
                status_code=200,
                content={"error": "Impossible de télécharger l'audio (Lien invalide ou protégé)"}
            )
        
        # Analyze with hybrid system
        result = analyze_audio_hybrid(audio_path)
        
        # Cleanup
        try:
            os.remove(audio_path)
        except:
            pass
        
        if "error" in result:
            return JSONResponse(status_code=200, content=result)
        
        return JSONResponse(status_code=200, content=result)
        
    except Exception as e:
        logger.error(f"API Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Analyze music from an uploaded audio file
    """
    try:
        logger.info(f"Received file: {file.filename}")
        
        # Check file extension
        allowed_extensions = {"mp3", "wav", "mp4", "m4a", "webm"}
        file_ext = file.filename.split('.')[-1].lower()
        
        if file_ext not in allowed_extensions:
            return JSONResponse(
                status_code=400,
                content={"error": f"Format non supporté ({file_ext}). Utilisez: {', '.join(allowed_extensions)}"}
            )
        
        # Save file temporarily
        temp_dir = "/tmp" if os.path.exists("/tmp") else os.path.dirname(os.path.abspath(__file__))
        temp_path = f"{temp_dir}/{uuid.uuid4()}.{file_ext}"
        
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        logger.info(f"File saved: {temp_path}")
        
        # Analyze with hybrid system
        result = analyze_audio_hybrid(temp_path)
        
        # Cleanup
        try:
            os.remove(temp_path)
        except:
            pass
        
        if "error" in result:
            return JSONResponse(status_code=200, content=result)
        
        return JSONResponse(status_code=200, content=result)
        
    except Exception as e:
        logger.error(f"Upload Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
