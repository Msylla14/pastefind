import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
from acrcloud.recognizer import ACRCloudRecognizer
import asyncio
from typing import Optional

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production: ["https://pastefind.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modèle de données
class VideoURL(BaseModel):
    url: str

# Configuration ACRCloud depuis les variables d'environnement
ACRCLOUD_CONFIG = {
    'host': os.getenv('ACRCLOUD_HOST', 'identify-eu-west-1.acrcloud.com'),
    'access_key': os.getenv('ACRCLOUD_ACCESS_KEY', ''),
    'access_secret': os.getenv('ACRCLOUD_SECRET_KEY', ''),
    'timeout': 10
}

def download_audio(url: str) -> Optional[str]:
    """
    Télécharge l'audio d'une vidéo YouTube/Facebook/TikTok
    Retourne le chemin du fichier audio ou None en cas d'erreur
    """
    try:
        # Options yt-dlp pour télécharger l'audio
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': '/tmp/%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get('id', 'unknown')
            audio_file = f"/tmp/{video_id}.mp3"
            
            logger.info(f"Audio téléchargé : {audio_file}")
            return audio_file
            
    except Exception as e:
        logger.error(f"Erreur téléchargement audio: {str(e)}")
        return None

def identify_music_with_acrcloud(audio_file: str) -> dict:
    """
    Identifie la musique avec ACRCloud
    Retourne les informations de la chanson ou une erreur
    """
    try:
        # Vérifier que les clés API sont configurées
        if not ACRCLOUD_CONFIG['access_key'] or not ACRCLOUD_CONFIG['access_secret']:
            logger.error("Clés API ACRCloud manquantes dans les variables d'environnement")
            return {'error': 'Configuration ACRCloud manquante'}
        
        # Créer le recognizer ACRCloud
        recognizer = ACRCloudRecognizer(ACRCLOUD_CONFIG)
        
        # Reconnaissance avec le fichier audio
        logger.info(f"Reconnaissance ACRCloud du fichier: {audio_file}")
        result = recognizer.recognize_by_file(audio_file, 0)
        
        # Parser le résultat JSON
        import json
        result_data = json.loads(result)
        
        logger.info(f"Résultat ACRCloud: {result_data}")
        
        # Vérifier le statut de la réponse
        status = result_data.get('status', {})
        if status.get('code') != 0:
            error_msg = status.get('msg', 'Musique non identifiée')
            logger.warning(f"ACRCloud: {error_msg}")
            return {'error': f'Musique non identifiée: {error_msg}'}
        
        # Extraire les métadonnées de la musique
        metadata = result_data.get('metadata', {})
        music_list = metadata.get('music', [])
        
        if not music_list:
            return {'error': 'Aucune musique trouvée'}
        
        # Prendre la première correspondance (meilleur score)
        music = music_list[0]
        
        # Extraire les informations
        title = music.get('title', 'Unknown Title')
        artists = music.get('artists', [])
        artist_name = artists[0].get('name', 'Unknown Artist') if artists else 'Unknown Artist'
        album = music.get('album', {})
        album_name = album.get('name', '')
        
        # Image de couverture
        cover_art = ''
        if album:
            cover_art = album.get('cover', '')
        
        # Liens externes (Spotify, YouTube Music, Apple Music)
        external_metadata = music.get('external_metadata', {})
        spotify_url = ''
        youtube_url = ''
        apple_music_url = ''
        
        # Spotify
        if 'spotify' in external_metadata:
            spotify_data = external_metadata['spotify']
            if isinstance(spotify_data, dict):
                spotify_url = spotify_data.get('track', {}).get('external_urls', {}).get('spotify', '')
            elif isinstance(spotify_data, list) and spotify_data:
                spotify_url = spotify_data[0].get('track', {}).get('external_urls', {}).get('spotify', '')
        
        # YouTube Music
        if 'youtube' in external_metadata:
            youtube_data = external_metadata['youtube']
            if isinstance(youtube_data, dict):
                video_id = youtube_data.get('vid', '')
                if video_id:
                    youtube_url = f"https://music.youtube.com/watch?v={video_id}"
        
        # Apple Music
        if 'apple_music' in external_metadata:
            apple_data = external_metadata['apple_music']
            if isinstance(apple_data, dict):
                apple_music_url = apple_data.get('url', '')
            elif isinstance(apple_data, list) and apple_data:
                apple_music_url = apple_data[0].get('url', '')
        
        # Construire la réponse
        return {
            'title': title,
            'subtitle': artist_name,
            'album': album_name,
            'image': cover_art,
            'spotify_url': spotify_url,
            'youtube_url': youtube_url,
            'apple_music': apple_music_url
        }
        
    except Exception as e:
        logger.error(f"Erreur ACRCloud: {str(e)}")
        return {'error': f'Erreur reconnaissance: {str(e)}'}

async def analyze_video(url: str) -> dict:
    """
    Analyse une vidéo et identifie la musique
    """
    try:
        # Étape 1: Télécharger l'audio
        logger.info(f"Analyse de: {url}")
        audio_file = await asyncio.get_event_loop().run_in_executor(
            None, download_audio, url
        )
        
        if not audio_file:
            return {'error': 'Impossible de télécharger l\'audio'}
        
        # Étape 2: Identifier la musique avec ACRCloud
        result = await asyncio.get_event_loop().run_in_executor(
            None, identify_music_with_acrcloud, audio_file
        )
        
        # Étape 3: Nettoyer le fichier temporaire
        try:
            if os.path.exists(audio_file):
                os.remove(audio_file)
                logger.info(f"Fichier temporaire supprimé: {audio_file}")
        except Exception as e:
            logger.warning(f"Impossible de supprimer {audio_file}: {str(e)}")
        
        return result
        
    except Exception as e:
        logger.error(f"Erreur analyse vidéo: {str(e)}")
        return {'error': str(e)}

# Routes
@app.get("/")
async def root():
    return {
        "message": "PasteFind API - ACRCloud Music Recognition",
        "version": "2.0",
        "status": "active",
        "recognition": "ACRCloud"
    }

@app.post("/api/analyze")
async def analyze_route(video: VideoURL):
    """
    Endpoint principal pour analyser une vidéo et identifier la musique
    """
    try:
        result = await analyze_video(video.url)
        
        if result is None:
            raise HTTPException(status_code=400, detail="Impossible d'analyser la vidéo")
        
        # Si erreur, retourner quand même 200 avec le message d'erreur
        if 'error' in result:
            return {
                'error': result['error'],
                'title': '',
                'subtitle': '',
                'image': '',
                'spotify_url': '',
                'youtube_url': '',
                'apple_music': ''
            }
        
        return result
        
    except Exception as e:
        logger.error(f"Erreur endpoint /api/analyze: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """
    Health check pour Render
    """
    acrcloud_configured = bool(ACRCLOUD_CONFIG['access_key'] and ACRCLOUD_CONFIG['access_secret'])
    return {
        "status": "healthy",
        "acrcloud_configured": acrcloud_configured,
        "host": ACRCLOUD_CONFIG['host']
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
