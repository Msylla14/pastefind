from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
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
from youtube_functions import extract_youtube_id, get_youtube_metadata, identify_music_from_youtube_metadata, download_youtube_audio_rapidapi

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

# YouTube API Configuration
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', '')
YOUTUBE_API_URL = 'https://www.googleapis.com/youtube/v3'

# RapidAPI Configuration (for YouTube download fallback)
RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY', '')
RAPIDAPI_YOUTUBE_URL = 'https://youtube-mp36.p.rapidapi.com'

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
        
        # YouTube handling with API
        if 'youtube.com' in url or 'youtu.be' in url:
            logger.info("YouTube URL detected, using YouTube API")
            
            # Extract video ID
            video_id = extract_youtube_id(url)
            if not video_id:
                return JSONResponse(
                    status_code=200,
                    content={"error": "❌ Lien YouTube invalide. Vérifiez le lien et réessayez."}
                )
            
            # Method 1: Try to identify from YouTube metadata (fast, free)
            if YOUTUBE_API_KEY:
                logger.info("Trying YouTube metadata identification...")
                metadata = get_youtube_metadata(video_id, YOUTUBE_API_KEY)
                if metadata:
                    music_info = identify_music_from_youtube_metadata(metadata)
                    if music_info:
                        logger.info(f"Music identified from YouTube metadata: {music_info}")
                        
                        # Generate links
                        title = music_info['title']
                        artist = music_info['artist']
                        query = urllib.parse.quote(f"{title} {artist}")
                        
                        return JSONResponse(
                            status_code=200,
                            content={
                                "title": title,
                                "subtitle": artist,
                                "image": metadata.get('thumbnail', ''),
                                "spotify_url": f"https://open.spotify.com/search/{query}",
                                "youtube_url": url,
                                "apple_music": f"https://music.apple.com/search?term={query}",
                                "service": "youtube_metadata"
                            }
                        )
            
            # Method 2: Try RapidAPI download (if configured)
            if RAPIDAPI_KEY:
                logger.info("Trying RapidAPI YouTube download...")
                audio_path = download_youtube_audio_rapidapi(video_id, RAPIDAPI_KEY)
                if audio_path:
                    # Continue with normal analysis flow
                    logger.info(f"YouTube audio downloaded via RapidAPI: {audio_path}")
                    # Fall through to normal analysis below
                else:
                    logger.warning("RapidAPI download failed")
            
            # Method 3: Fallback - suggest manual download
            if not YOUTUBE_API_KEY and not RAPIDAPI_KEY:
                return JSONResponse(
                    status_code=200,
                    content={
                        "error": "🚫 YouTube bloque l'extraction audio pour des raisons de droits d'auteur.\n\n💡 Solution : Téléchargez la vidéo YouTube avec une application (SnapTube, VidMate, etc.) puis utilisez le mode 'Fichier Local' pour analyser le fichier MP3/MP4."
                    }
                )
            
            # If we got here without audio_path, metadata method failed
            if 'audio_path' not in locals():
                return JSONResponse(
                    status_code=200,
                    content={
                        "error": "⚠️ Impossible d'identifier la musique automatiquement.\n\n💡 Solution : Téléchargez la vidéo et utilisez le mode 'Fichier Local'."
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

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """
    Page de politique de confidentialité pour Google Play Store
    """
    html_content = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Politique de Confidentialité - PasteFind</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
        }
        h1 {
            color: #E91E63;
            border-bottom: 3px solid #9C27B0;
            padding-bottom: 10px;
        }
        h2 {
            color: #9C27B0;
            margin-top: 30px;
        }
        .last-updated {
            color: #666;
            font-style: italic;
            margin-bottom: 30px;
        }
        .contact {
            background: #f5f5f5;
            padding: 15px;
            border-left: 4px solid #E91E63;
            margin-top: 30px;
        }
    </style>
</head>
<body>
    <h1>Politique de Confidentialité - PasteFind</h1>
    <p class="last-updated">Dernière mise à jour : 19 février 2026</p>

    <h2>1. Introduction</h2>
    <p>
        Bienvenue sur PasteFind. Nous respectons votre vie privée et nous nous engageons à protéger vos données personnelles. 
        Cette politique de confidentialité explique comment nous collectons, utilisons et protégeons vos informations lorsque vous utilisez notre application mobile et notre site web.
    </p>

    <h2>2. Données Collectées</h2>
    <p>PasteFind collecte les types de données suivants :</p>
    <ul>
        <li><strong>Enregistrements audio</strong> : Lorsque vous utilisez la fonctionnalité microphone, nous enregistrons jusqu'à 10 secondes d'audio pour identifier la musique.</li>
        <li><strong>URLs vidéo</strong> : Les liens TikTok, YouTube, Facebook ou Instagram que vous collez pour analyse.</li>
        <li><strong>Historique de recherche</strong> : Les résultats de vos recherches musicales sont stockés localement sur votre appareil (ou dans le cloud si vous êtes connecté).</li>
        <li><strong>Informations de compte</strong> : Si vous créez un compte, nous collectons votre email et votre nom via Google Sign-In ou Apple Sign-In.</li>
        <li><strong>Données d'utilisation</strong> : Statistiques anonymes sur l'utilisation de l'application (nombre de recherches, fonctionnalités utilisées).</li>
    </ul>

    <h2>3. Utilisation des Données</h2>
    <p>Nous utilisons vos données pour :</p>
    <ul>
        <li>Identifier les morceaux de musique à partir d'enregistrements audio ou de vidéos</li>
        <li>Améliorer la précision de notre service de reconnaissance musicale</li>
        <li>Synchroniser votre historique de recherche entre vos appareils (si vous êtes connecté)</li>
        <li>Gérer votre abonnement Premium et vos paiements</li>
        <li>Afficher des publicités personnalisées (utilisateurs gratuits uniquement)</li>
        <li>Analyser l'utilisation de l'application pour améliorer nos services</li>
    </ul>

    <h2>4. Partage des Données</h2>
    <p>Nous ne vendons jamais vos données personnelles. Nous partageons vos données uniquement avec :</p>
    <ul>
        <li><strong>Services d'identification musicale</strong> : ACRCloud, AudD.io, YouTube Data API pour analyser les enregistrements audio et vidéos</li>
        <li><strong>Google AdMob</strong> : Pour afficher des publicités aux utilisateurs gratuits (conformément à la politique de Google)</li>
        <li><strong>Stripe</strong> : Pour traiter les paiements des abonnements Premium (conformément à la politique de Stripe)</li>
        <li><strong>Hébergement</strong> : Render.com pour héberger notre backend et base de données</li>
    </ul>

    <h2>5. Conservation des Données</h2>
    <ul>
        <li><strong>Enregistrements audio</strong> : Supprimés immédiatement après identification (non stockés)</li>
        <li><strong>Historique de recherche</strong> : Conservé indéfiniment (sauf suppression manuelle par l'utilisateur)</li>
        <li><strong>Données de compte</strong> : Conservées tant que votre compte est actif</li>
        <li><strong>Logs serveur</strong> : Conservés 30 jours pour débogage et sécurité</li>
    </ul>

    <h2>6. Vos Droits (RGPD)</h2>
    <p>Conformément au Règlement Général sur la Protection des Données (RGPD), vous avez le droit de :</p>
    <ul>
        <li><strong>Accès</strong> : Demander une copie de vos données personnelles</li>
        <li><strong>Rectification</strong> : Corriger des données inexactes</li>
        <li><strong>Suppression</strong> : Supprimer votre compte et toutes vos données</li>
        <li><strong>Portabilité</strong> : Exporter vos données dans un format lisible</li>
        <li><strong>Opposition</strong> : Refuser le traitement de vos données à des fins marketing</li>
    </ul>

    <h2>7. Sécurité</h2>
    <p>
        Nous mettons en œuvre des mesures de sécurité techniques et organisationnelles pour protéger vos données :
    </p>
    <ul>
        <li>Chiffrement HTTPS pour toutes les communications</li>
        <li>Authentification OAuth sécurisée (Google/Apple)</li>
        <li>Base de données PostgreSQL avec accès restreint</li>
        <li>Audits de sécurité réguliers</li>
    </ul>

    <h2>8. Cookies et Technologies Similaires</h2>
    <p>
        Nous utilisons des cookies et technologies similaires pour :
    </p>
    <ul>
        <li>Maintenir votre session de connexion</li>
        <li>Mémoriser vos préférences (thème sombre/clair)</li>
        <li>Analyser l'utilisation du site web (Google Analytics)</li>
        <li>Afficher des publicités personnalisées (Google AdMob)</li>
    </ul>

    <h2>9. Services Tiers</h2>
    <p>PasteFind utilise les services tiers suivants, chacun ayant sa propre politique de confidentialité :</p>
    <ul>
        <li><a href="https://www.acrcloud.com/privacy" target="_blank">ACRCloud Privacy Policy</a></li>
        <li><a href="https://audd.io/privacy" target="_blank">AudD.io Privacy Policy</a></li>
        <li><a href="https://policies.google.com/privacy" target="_blank">Google Privacy Policy</a> (YouTube Data API, AdMob, Sign-In)</li>
        <li><a href="https://www.apple.com/legal/privacy/" target="_blank">Apple Privacy Policy</a> (Sign-In)</li>
        <li><a href="https://stripe.com/privacy" target="_blank">Stripe Privacy Policy</a> (Paiements)</li>
    </ul>

    <h2>10. Modifications de cette Politique</h2>
    <p>
        Nous pouvons mettre à jour cette politique de confidentialité de temps en temps. 
        Nous vous informerons de tout changement important via l'application ou par email. 
        La date de "Dernière mise à jour" en haut de cette page indique quand la politique a été modifiée pour la dernière fois.
    </p>

    <h2>11. Contact</h2>
    <div class="contact">
        <p>Pour toute question concernant cette politique de confidentialité ou pour exercer vos droits, contactez-nous :</p>
        <p>
            <strong>Email</strong> : <a href="mailto:contact@pastefind.com">contact@pastefind.com</a><br>
            <strong>Site web</strong> : <a href="https://pastefind.onrender.com">https://pastefind.onrender.com</a>
        </p>
    </div>

    <hr style="margin-top: 50px; border: none; border-top: 1px solid #ddd;">
    <p style="text-align: center; color: #999; font-size: 14px;">
        © 2026 PasteFind. Tous droits réservés.
    </p>
</body>
</html>"""
    return HTMLResponse(content=html_content, status_code=200)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
