from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import yt_dlp
import asyncio
import logging
import tempfile
import os
from shazamio import Shazam

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VideoURL(BaseModel):
    url: str

async def identify_song(data: VideoURL):
    url = data.url
    logger.info(f"Analyzing URL: {url}")
    
    # yt-dlp options pour télécharger l'audio
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'extract_audio': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'outtmpl': '/tmp/%(id)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    audio_file = None
    
    try:
        # Étape 1 : Télécharger l'audio de la vidéo
        logger.info("Downloading audio from video...")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if not info:
                logger.error("No info returned from yt-dlp")
                return {"error": "Could not download video"}
            
            # Récupérer l'ID de la vidéo
            video_id = info.get('id', 'unknown')
            audio_file = f"/tmp/{video_id}.mp3"
            
            # Vérifier que le fichier existe
            if not os.path.exists(audio_file):
                logger.error(f"Audio file not found: {audio_file}")
                return {"error": "Could not extract audio from video"}
            
            logger.info(f"Audio downloaded: {audio_file}")
        
        # Étape 2 : Identifier la musique avec Shazam
        logger.info("Identifying music with Shazam...")
        shazam = Shazam()
        
        # Reconnaissance musicale
        result = await shazam.recognize(audio_file)
        
        # Nettoyer le fichier temporaire
        try:
            os.remove(audio_file)
        except:
            pass
        
        # Vérifier si Shazam a trouvé quelque chose
        if not result or 'track' not in result:
            logger.warning("Shazam could not identify the music")
            return {
                "error": "Music not recognized",
                "title": "Musique non identifiée",
                "subtitle": "Shazam n'a pas pu reconnaître cette musique",
                "image": "",
                "apple_music": "",
                "spotify_url": "",
                "youtube_url": url
            }
        
        track = result['track']
        
        # Extraire les informations
        title = track.get('title', 'Unknown Title')
        artist = track.get('subtitle', 'Unknown Artist')
        
        # Image de la pochette
        images = track.get('images', {})
        cover_art = images.get('coverart', '') if images else ''
        
        # Liens vers les plateformes
        apple_music_url = track.get('url', '')
        
        # Chercher le lien Spotify dans les sections
        spotify_url = ""
        youtube_music_url = ""
        
        sections = track.get('sections', [])
        for section in sections:
            if section.get('type') == 'SONG':
                metadata = section.get('metadata', [])
                for item in metadata:
                    if item.get('title') == 'Spotify':
                        spotify_url = item.get('text', '')
                    elif item.get('title') == 'YouTube':
                        youtube_music_url = item.get('text', '')
        
        # Construire la réponse
        logger.info(f"Successfully identified: {title} by {artist}")
        
        return {
            "title": title,
            "subtitle": artist,
            "image": cover_art,
            "apple_music": apple_music_url,
            "spotify_url": spotify_url,
            "youtube_url": youtube_music_url or url
        }
        
    except Exception as e:
        logger.error(f"Error during analysis: {e}")
        
        # Nettoyer le fichier en cas d'erreur
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except:
                pass
        
        return {"error": str(e)}

@app.get("/")
async def home():
    return {"message": "PasteFind API - Music Recognition Service", "status": "online"}

@app.post("/api/analyze")
async def analyze_route(video: VideoURL):
    result = await identify_song(video)
    
    if not result:
        raise HTTPException(status_code=400, detail="Analysis failed: No result")
    
    if "error" in result:
        return JSONResponse(content=result)
    
    return JSONResponse(content=result)
