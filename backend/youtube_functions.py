"""
YouTube API integration functions for PasteFind
"""
import re
import requests
import logging

logger = logging.getLogger(__name__)

def extract_youtube_id(url: str) -> str:
    """
    Extract YouTube video ID from various URL formats
    """
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/v\/([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def get_youtube_metadata(video_id: str, api_key: str) -> dict:
    """
    Get YouTube video metadata using YouTube Data API v3
    Returns: dict with title, description, tags, etc.
    """
    if not api_key:
        logger.error("YouTube API key not configured")
        return None
    
    url = f"https://www.googleapis.com/youtube/v3/videos"
    params = {
        'part': 'snippet,contentDetails',
        'id': video_id,
        'key': api_key
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get('items'):
            logger.error(f"No video found for ID: {video_id}")
            return None
        
        snippet = data['items'][0]['snippet']
        
        return {
            'title': snippet.get('title', ''),
            'description': snippet.get('description', ''),
            'channel': snippet.get('channelTitle', ''),
            'tags': snippet.get('tags', []),
            'thumbnail': snippet.get('thumbnails', {}).get('high', {}).get('url', '')
        }
    
    except Exception as e:
        logger.error(f"Error fetching YouTube metadata: {e}")
        return None


def identify_music_from_youtube_metadata(metadata: dict) -> dict:
    """
    Try to identify music from YouTube metadata (title, description, tags)
    This works for official music videos and videos with proper metadata
    """
    if not metadata:
        return None
    
    title = metadata.get('title', '')
    description = metadata.get('description', '')
    tags = metadata.get('tags', [])
    
    # Common patterns for music videos
    # Pattern 1: "Artist - Song Title (Official Video)"
    match = re.search(r'^(.+?)\s*[-–—]\s*(.+?)(?:\s*\(.*\))?$', title)
    if match:
        artist = match.group(1).strip()
        song = match.group(2).strip()
        
        # Clean up common suffixes
        song = re.sub(r'\s*\(.*?(Official|Music|Video|Audio|Lyric).*?\)\s*', '', song, flags=re.IGNORECASE)
        song = re.sub(r'\s*\[.*?(Official|Music|Video|Audio|Lyric).*?\]\s*', '', song, flags=re.IGNORECASE)
        
        return {
            'title': song,
            'artist': artist,
            'source': 'youtube_metadata',
            'confidence': 'high' if 'official' in title.lower() else 'medium'
        }
    
    # Pattern 2: Look for artist/song in description
    desc_lines = description.split('\n')
    for line in desc_lines[:5]:  # Check first 5 lines
        if 'artist:' in line.lower():
            artist_match = re.search(r'artist:\s*(.+)', line, re.IGNORECASE)
            if artist_match:
                artist = artist_match.group(1).strip()
        if 'song:' in line.lower() or 'title:' in line.lower():
            song_match = re.search(r'(?:song|title):\s*(.+)', line, re.IGNORECASE)
            if song_match:
                song = song_match.group(1).strip()
                
                # If we found both
                if 'artist' in locals() and 'song' in locals():
                    return {
                        'title': song,
                        'artist': artist,
                        'source': 'youtube_description',
                        'confidence': 'medium'
                    }
    
    return None


def download_youtube_audio_rapidapi(video_id: str, rapidapi_key: str) -> str:
    """
    Download YouTube audio using RapidAPI YouTube MP3 Downloader
    Returns: path to downloaded audio file
    """
    if not rapidapi_key:
        logger.error("RapidAPI key not configured")
        return None
    
    url = "https://youtube-mp36.p.rapidapi.com/dl"
    querystring = {"id": video_id}
    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": "youtube-mp36.p.rapidapi.com"
    }
    
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get('status') == 'ok':
            download_url = data.get('link')
            if download_url:
                # Download the audio file
                audio_response = requests.get(download_url, timeout=60)
                audio_response.raise_for_status()
                
                # Save to temp file
                import tempfile
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
                temp_file.write(audio_response.content)
                temp_file.close()
                
                logger.info(f"YouTube audio downloaded via RapidAPI: {temp_file.name}")
                return temp_file.name
        
        logger.error(f"RapidAPI download failed: {data}")
        return None
    
    except Exception as e:
        logger.error(f"Error downloading YouTube audio via RapidAPI: {e}")
        return None
