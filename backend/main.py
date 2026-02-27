from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from pydantic import BaseModel
import yt_dlp
import asyncio
import logging
import os
import uuid
import json
import urllib.parse
import requests
import re
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PasteFind API", version="3.0")

# AudD.io Configuration
AUDD_API_TOKEN = os.getenv('AUDD_API_TOKEN', '')
AUDD_API_URL = 'https://api.audd.io/'

# CORS - allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files directory (root of project)
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML_FILE = os.path.join(STATIC_DIR, 'index.html')

class VideoURL(BaseModel):
    url: str

# ─────────────────────────────────────────────
# HELPER: Clean tracking params from URL
# ─────────────────────────────────────────────
def clean_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        keys_to_remove = [k for k in query_params if k in ['fbclid', 'si', 'igsh', 'utm_source', 'utm_medium', 'utm_campaign']]
        for k in keys_to_remove:
            del query_params[k]
        new_query = urllib.parse.urlencode(query_params, doseq=True)
        return urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment
        ))
    except Exception as e:
        logger.warning(f"URL Cleaning failed: {e}")
        return url

# ─────────────────────────────────────────────
# HELPER: Analyze audio with AudD.io
# ─────────────────────────────────────────────
def analyze_with_audd(file_path: str) -> dict:
    """Send audio file to AudD.io API for music recognition."""
    if not AUDD_API_TOKEN:
        logger.warning("[AudD] No API token configured")
        return {"error": "API token not configured"}

    try:
        logger.info(f"[AudD] Analyzing: {file_path}")
        file_size = os.path.getsize(file_path)
        logger.info(f"[AudD] File size: {file_size} bytes")

        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = {
                'api_token': AUDD_API_TOKEN,
                'return': 'apple_music,spotify,deezer'
            }
            response = requests.post(AUDD_API_URL, files=files, data=data, timeout=60)
            result = response.json()

        logger.info(f"[AudD] Status: {result.get('status')}")

        if result.get('status') != 'success':
            error_msg = result.get('error', {})
            if isinstance(error_msg, dict):
                error_msg = error_msg.get('error_message', 'Unknown error')
            return {"error": f"AudD error: {error_msg}"}

        if result.get('result') is None:
            return {"error": "no_match"}

        music = result['result']
        title = music.get('title', 'Unknown Title')
        artist = music.get('artist', 'Unknown Artist')

        # --- Cover art (priority: Spotify > Apple Music > Deezer) ---
        image = ''
        spotify_data = music.get('spotify') or {}
        if spotify_data and 'album' in spotify_data:
            images = spotify_data['album'].get('images', [])
            if images:
                image = images[0].get('url', '')

        if not image:
            apple_data = music.get('apple_music') or {}
            artwork = apple_data.get('artwork', {})
            if artwork:
                url_template = artwork.get('url', '')
                if url_template:
                    image = url_template.replace('{w}', '600').replace('{h}', '600')

        if not image:
            deezer_data = music.get('deezer') or {}
            album_data = deezer_data.get('album') or {}
            image = album_data.get('cover_xl', '') or album_data.get('cover_big', '')

        # --- External links ---
        spotify_url = ''
        apple_music_url = ''

        if spotify_data:
            ext_urls = spotify_data.get('external_urls', {})
            spotify_url = ext_urls.get('spotify', '')

        apple_data = music.get('apple_music') or {}
        if apple_data:
            apple_music_url = apple_data.get('url', '')

        # YouTube search fallback
        query = urllib.parse.quote(f"{title} {artist}")
        youtube_url = f"https://www.youtube.com/results?search_query={query}"

        if not spotify_url:
            spotify_url = f"https://open.spotify.com/search/{query}"

        if not apple_music_url:
            apple_music_url = f"https://music.apple.com/search?term={query}"

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
        logger.error("[AudD] Timeout")
        return {"error": "AudD timeout"}
    except Exception as e:
        logger.error(f"[AudD] Exception: {e}")
        return {"error": str(e)}

# ─────────────────────────────────────────────
# HELPER: Download audio with yt-dlp
# ─────────────────────────────────────────────
def download_audio(url: str) -> str | None:
    """Download audio from URL using yt-dlp. Returns path to MP3 file."""
    temp_dir = "/tmp"
    output_id = str(uuid.uuid4())
    output_template = f"{temp_dir}/{output_id}.%(ext)s"

    # Detect platform
    is_facebook = 'facebook.com' in url or 'fb.watch' in url or 'fb.com' in url
    is_instagram = 'instagram.com' in url
    is_tiktok = 'tiktok.com' in url or 'vm.tiktok.com' in url
    is_youtube = 'youtube.com' in url or 'youtu.be' in url

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'retries': 3,
        'fragment_retries': 3,
        'nocheckcertificate': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'postprocessor_args': ['-t', '30'],  # Only first 30 seconds
    }

    # Platform-specific headers
    if is_facebook or is_instagram:
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.facebook.com/' if is_facebook else 'https://www.instagram.com/',
        }
        ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'

    elif is_tiktok:
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
        }

    elif is_youtube:
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"[yt-dlp] Downloading: {url}")
            ydl.download([url])

        # Find the output file
        mp3_path = f"{temp_dir}/{output_id}.mp3"
        if os.path.exists(mp3_path):
            logger.info(f"[yt-dlp] Downloaded: {mp3_path} ({os.path.getsize(mp3_path)} bytes)")
            return mp3_path

        # Search for any file with our ID
        for f in os.listdir(temp_dir):
            if f.startswith(output_id):
                full_path = f"{temp_dir}/{f}"
                logger.info(f"[yt-dlp] Found file: {full_path}")
                return full_path

        logger.error("[yt-dlp] No output file found")
        return None

    except Exception as e:
        logger.error(f"[yt-dlp] Error: {e}")
        return None

# ─────────────────────────────────────────────
# HELPER: Truncate large files for AudD
# ─────────────────────────────────────────────
def truncate_audio_if_needed(file_path: str, max_mb: int = 8) -> str:
    """If file is too large, truncate to first 30 seconds using ffmpeg."""
    file_size = os.path.getsize(file_path)
    max_bytes = max_mb * 1024 * 1024

    if file_size <= max_bytes:
        return file_path

    logger.info(f"[Truncate] File too large ({file_size} bytes), truncating...")
    truncated_path = file_path.replace('.mp3', '_short.mp3').replace('.mp4', '_short.mp3').replace('.m4a', '_short.mp3').replace('.wav', '_short.mp3')

    # Try to use ffmpeg
    ffmpeg_paths = [
        '/var/www/pastefind-backend/bin/ffmpeg',
        '/usr/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        'ffmpeg'
    ]

    for ffmpeg in ffmpeg_paths:
        try:
            ret = os.system(f'{ffmpeg} -i "{file_path}" -t 30 -acodec libmp3lame -ab 128k "{truncated_path}" -y -loglevel quiet 2>/dev/null')
            if ret == 0 and os.path.exists(truncated_path):
                logger.info(f"[Truncate] Truncated to: {truncated_path}")
                return truncated_path
        except:
            continue

    logger.warning("[Truncate] ffmpeg not available, using original file")
    return file_path

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML interface."""
    try:
        with open(HTML_FILE, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read(), status_code=200)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>PasteFind</h1><p>Interface file not found. Please redeploy.</p>",
            status_code=404
        )

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "3.0",
        "audd_configured": bool(AUDD_API_TOKEN),
        "static_dir": STATIC_DIR,
        "html_exists": os.path.exists(HTML_FILE)
    }

@app.get("/logo.png")
async def get_logo():
    path = os.path.join(STATIC_DIR, 'logo.png')
    return FileResponse(path) if os.path.exists(path) else JSONResponse({"error": "not found"}, 404)

@app.get("/favicon.png")
async def get_favicon():
    path = os.path.join(STATIC_DIR, 'favicon.png')
    return FileResponse(path) if os.path.exists(path) else JSONResponse({"error": "not found"}, 404)

@app.get("/bg-wave.png")
async def get_bg_wave():
    path = os.path.join(STATIC_DIR, 'bg-wave.png')
    return FileResponse(path) if os.path.exists(path) else JSONResponse({"error": "not found"}, 404)

@app.post("/api/analyze")
async def analyze_video(data: VideoURL):
    """Analyze music from a video URL (Facebook, TikTok, Instagram, YouTube, etc.)"""
    try:
        url = clean_url(data.url.strip())
        logger.info(f"[/api/analyze] URL: {url}")

        if not url or not url.startswith(('http://', 'https://')):
            return JSONResponse(status_code=200, content={
                "error": "❌ Lien invalide. Veuillez coller un lien complet (commençant par https://)"
            })

        # Download audio
        audio_path = download_audio(url)

        if not audio_path:
            platform = "ce site"
            if 'facebook.com' in url or 'fb.watch' in url:
                platform = "Facebook"
            elif 'instagram.com' in url:
                platform = "Instagram"
            elif 'tiktok.com' in url:
                platform = "TikTok"
            elif 'youtube.com' in url or 'youtu.be' in url:
                platform = "YouTube"

            return JSONResponse(status_code=200, content={
                "error": f"❌ Impossible de télécharger l'audio depuis {platform}.\n\n💡 Essayez de télécharger la vidéo sur votre appareil, puis utilisez l'onglet 'Fichier Local'."
            })

        # Truncate if too large
        audio_path = truncate_audio_if_needed(audio_path)

        # Analyze
        result = analyze_with_audd(audio_path)

        # Cleanup
        try:
            os.remove(audio_path)
            if audio_path.endswith('_short.mp3'):
                original = audio_path.replace('_short.mp3', '.mp3')
                if os.path.exists(original):
                    os.remove(original)
        except:
            pass

        if result.get("error") == "no_match":
            return JSONResponse(status_code=200, content={
                "error": "🎵 Musique non reconnue. Essayez avec une partie différente de la vidéo."
            })

        if "error" in result:
            return JSONResponse(status_code=200, content=result)

        return JSONResponse(status_code=200, content=result)

    except Exception as e:
        logger.error(f"[/api/analyze] Error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Erreur serveur: {str(e)}"})


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Analyze music from an uploaded audio/video file."""
    try:
        filename = file.filename or "upload"
        logger.info(f"[/api/upload] File: {filename}")

        # Check extension
        allowed_extensions = {"mp3", "wav", "mp4", "m4a", "webm", "ogg", "aac", "flac"}
        file_ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp3'

        if file_ext not in allowed_extensions:
            return JSONResponse(status_code=400, content={
                "error": f"❌ Format non supporté : .{file_ext}\n\nFormats acceptés : MP3, MP4, WAV, M4A, WEBM, OGG, AAC, FLAC"
            })

        # Save to temp
        temp_path = f"/tmp/{uuid.uuid4()}.{file_ext}"
        content = await file.read()

        if len(content) == 0:
            return JSONResponse(status_code=400, content={"error": "❌ Le fichier est vide."})

        with open(temp_path, "wb") as f_out:
            f_out.write(content)

        logger.info(f"[/api/upload] Saved: {temp_path} ({len(content)} bytes)")

        # Truncate if too large
        temp_path = truncate_audio_if_needed(temp_path)

        # Analyze
        result = analyze_with_audd(temp_path)

        # Cleanup
        try:
            os.remove(temp_path)
        except:
            pass

        if result.get("error") == "no_match":
            return JSONResponse(status_code=200, content={
                "error": "🎵 Musique non reconnue dans ce fichier. Essayez un extrait différent."
            })

        if "error" in result:
            return JSONResponse(status_code=200, content=result)

        return JSONResponse(status_code=200, content=result)

    except Exception as e:
        logger.error(f"[/api/upload] Error: {e}")
        return JSONResponse(status_code=500, content={"error": f"Erreur serveur: {str(e)}"})


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """Privacy policy page."""
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Politique de Confidentialité - PasteFind</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; }
        h1 { color: #E91E63; border-bottom: 3px solid #9C27B0; padding-bottom: 10px; }
        h2 { color: #9C27B0; margin-top: 30px; }
    </style>
</head>
<body>
    <h1>Politique de Confidentialité - PasteFind</h1>
    <p><em>Dernière mise à jour : 27 février 2026</em></p>
    <h2>1. Introduction</h2>
    <p>PasteFind respecte votre vie privée. Cette politique explique comment nous collectons et utilisons vos données.</p>
    <h2>2. Données collectées</h2>
    <p>Nous collectons : enregistrements audio temporaires (supprimés après identification), URLs vidéo soumises, historique local de recherche.</p>
    <h2>3. Utilisation</h2>
    <p>Les données sont utilisées uniquement pour identifier la musique via les services AudD.io et ACRCloud.</p>
    <h2>4. Contact</h2>
    <p>Email : <a href="mailto:contact@pastefind.com">contact@pastefind.com</a></p>
    <p>© 2026 PasteFind. Tous droits réservés.</p>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
