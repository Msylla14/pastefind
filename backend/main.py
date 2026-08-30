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
import shutil
import subprocess

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PasteFind API", version="3.0")

# AudD.io Configuration
AUDD_API_TOKEN = os.getenv('AUDD_API_TOKEN', '')
AUDD_API_URL = 'https://api.audd.io/'

# Hard server-side cap on uploaded file size (bytes). The frontend also
# checks 50 MB client-side, but that check is trivial to bypass by calling
# the API directly, so the real limit has to live here.
MAX_UPLOAD_BYTES = 60 * 1024 * 1024

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
# Dernière erreur de téléchargement, conservée pour les journaux du serveur.
LAST_DOWNLOAD_ERROR: dict[str, str] = {}

# Clé du point de diagnostic temporaire /diag.
# Elle vient UNIQUEMENT de l'environnement Render : le dépôt est public, une clé
# écrite en dur ici laisserait n'importe qui déclencher des téléchargements et
# consommer le forfait du proxy. Sans variable DIAG_KEY, /diag n'existe pas.
DIAG_KEY = os.getenv('DIAG_KEY', '').strip()


def trouver_dossier_ffmpeg() -> str | None:
    """Retourne le dossier contenant a la fois ffmpeg et ffprobe, ou None.

    yt-dlp cherche ffmpeg/ffprobe dans le PATH. Sur Render le PATH n'est pas
    fiable : si ffprobe est introuvable, le post-traitement echoue avec
    « unable to obtain file audio codec with ffprobe » et le telechargement
    est perdu alors que la video a bien ete recuperee. On lui donne donc le
    chemin explicitement.
    """
    ici = os.path.dirname(os.path.abspath(__file__))
    candidats = [
        os.path.join(ici, 'bin'),
        '/opt/render/project/src/backend/bin',
        '/opt/render/project/src/bin',
        '/var/www/pastefind-backend/bin',
        '/usr/local/bin',
        '/usr/bin',
    ]
    for dossier in candidats:
        f = os.path.join(dossier, 'ffmpeg')
        p = os.path.join(dossier, 'ffprobe')
        if os.path.isfile(f) and os.path.isfile(p):
            return dossier
    f = shutil.which('ffmpeg')
    p = shutil.which('ffprobe')
    if f and p:
        return os.path.dirname(f)
    return None


FFMPEG_DIR = trouver_dossier_ffmpeg()
logger.info(f"[ffmpeg] dossier retenu : {FFMPEG_DIR}")


# ─────────────────────────────────────────────
# Proxy et cookies : deux leviers pour contourner les blocages des plateformes.
# Rien n'est ecrit dans le code : tout vient des variables d'environnement
# Render, pour qu'aucun secret ne se retrouve dans le depot.
#
#   PROXY_URL   ex. http://utilisateur:motdepasse@hote:port  (proxy residentiel)
#   COOKIES_B64 contenu d'un fichier cookies.txt encode en base64
# ─────────────────────────────────────────────
PROXY_URL = os.getenv('PROXY_URL', '').strip()
COOKIES_PATH = '/tmp/pf_cookies.txt'

# Ciblage du proxy (DataImpulse) : le pays et la persistance de l'IP se
# demandent en suffixant le NOM D'UTILISATEUR, pas l'adresse.
#   login__cr.it            -> sortir par une IP italienne
#   login__cr.it;sessid.42  -> garder la meme IP pendant 30 minutes
# Utile parce qu'une session TikTok creee depuis l'Italie est refusee si la
# requete arrive depuis une IP d'un autre pays, ou si l'IP change a chaque appel.
PROXY_COUNTRY = os.getenv('PROXY_COUNTRY', '').strip().lower()
PROXY_SESSID = os.getenv('PROXY_SESSID', '').strip()

# Pays de sortie essayes successivement pour TikTok.
TIKTOK_COUNTRIES = [c.strip().lower() for c in
                    os.getenv('TIKTOK_COUNTRIES', 'it,fr,de,gb,us').split(',') if c.strip()]


def _proxy_cible(url: str, pays: str | None = None, sessid: str | None = None) -> str:
    """Ajoute le ciblage pays/session au nom d'utilisateur du proxy."""
    pays = PROXY_COUNTRY if pays is None else pays
    sessid = PROXY_SESSID if sessid is None else sessid
    if not url or (not pays and not sessid):
        return url
    try:
        p = urllib.parse.urlsplit(url)
        if not p.username or '__' in p.username:
            return url
        suffixe = ''
        if pays:
            suffixe += f'__cr.{pays}'
        if sessid:
            suffixe += (';' if suffixe else '__') + f'sessid.{sessid}'
        utilisateur = urllib.parse.quote(p.username + suffixe, safe='._;,-')
        secret = urllib.parse.quote(p.password or '', safe='')
        hote = p.hostname + (f':{p.port}' if p.port else '')
        return urllib.parse.urlunsplit(
            (p.scheme, f'{utilisateur}:{secret}@{hote}', p.path, p.query, p.fragment))
    except Exception as e:
        logger.error(f"[proxy] ciblage impossible : {e}")
        return url


def _preparer_cookies() -> str | None:
    """Deux facons de fournir les cookies, la plus simple d'abord.

    1. Un « Secret File » Render nomme cookies.txt : monte en lecture seule
       dans /etc/secrets/. On le recopie dans /tmp car yt-dlp a besoin de
       pouvoir reecrire le fichier.
    2. La variable COOKIES_B64 : le meme fichier encode en base64.
    """
    import glob
    # set() : un meme fichier peut correspondre aux deux motifs, sans quoi les
    # cookies seraient ecrits en double.
    sources = sorted(set(glob.glob('/etc/secrets/*cookies*')) | set(glob.glob('/etc/secrets/*.txt')))
    if sources:
        try:
            lignes = 0
            with open(COOKIES_PATH, 'w', encoding='utf-8') as sortie:
                sortie.write('# Netscape HTTP Cookie File\n')
                for source in sources:
                    with open(source, encoding='utf-8', errors='replace') as f:
                        for ligne in f:
                            nue = ligne.strip()
                            if not nue:
                                continue
                            # ATTENTION : les lignes « #HttpOnly_… » sont de VRAIS
                            # cookies, pas des commentaires. Ce sont meme les plus
                            # importants (sessionid de TikTok, par exemple). Les
                            # jeter revient a envoyer un fichier deconnecte.
                            if nue.startswith('#') and not nue.startswith('#HttpOnly_'):
                                continue
                            sortie.write(ligne if ligne.endswith('\n') else ligne + '\n')
                            lignes += 1
            os.chmod(COOKIES_PATH, 0o600)
            logger.info(f"[cookies] {lignes} lignes reprises depuis {len(sources)} fichier(s) secret(s)")
            if lignes:
                return COOKIES_PATH
        except Exception as e:
            logger.error(f"[cookies] fusion impossible : {e}")

    brut = os.getenv('COOKIES_B64', '').strip()
    if not brut:
        return None
    try:
        import base64
        with open(COOKIES_PATH, 'wb') as f:
            f.write(base64.b64decode(brut))
        os.chmod(COOKIES_PATH, 0o600)
        logger.info("[cookies] fichier de cookies ecrit depuis COOKIES_B64")
        return COOKIES_PATH
    except Exception as e:
        logger.error(f"[cookies] illisible : {e}")
        return None


COOKIES_FILE = _preparer_cookies()
PROXY_EFFECTIF = _proxy_cible(PROXY_URL)
logger.info(
    f"[reseau] proxy={'oui' if PROXY_EFFECTIF else 'non'}"
    f" pays={PROXY_COUNTRY or '-'} sessid={PROXY_SESSID or '-'}"
    f" cookies={'oui' if COOKIES_FILE else 'non'}")


def appliquer_reseau(opts: dict) -> dict:
    """Ajoute proxy et cookies aux options yt-dlp s'ils sont configures."""
    if PROXY_EFFECTIF:
        opts['proxy'] = PROXY_EFFECTIF
    if COOKIES_FILE:
        opts['cookiefile'] = COOKIES_FILE
    if FFMPEG_DIR:
        opts['ffmpeg_location'] = FFMPEG_DIR
    return opts


def derouler_lien_court(url: str) -> str:
    """Transforme un lien court en son adresse complete.

    Le bouton « Partager » de TikTok donne vm.tiktok.com/XXXX/, et c'est donc
    la forme que collent les utilisateurs. Or l'extracteur du lien court ne
    passe pas par l'imitation de navigateur et se fait refuser. On deroule donc
    la redirection nous-memes, en passant par le proxy, avant de confier
    l'adresse complete a yt-dlp.
    """
    if not re.search(r'(vm|vt)\.tiktok\.com|fb\.watch|(www\.)?tiktok\.com/t/', url):
        return url
    proxies = {'http': PROXY_EFFECTIF, 'https': PROXY_EFFECTIF} if PROXY_EFFECTIF else None
    entetes = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
                             'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
                             'Mobile/15E148 Safari/604.1'}
    try:
        r = requests.get(url, headers=entetes, proxies=proxies,
                         allow_redirects=True, timeout=20)
        complet = r.url.split('?')[0]
        if complet and complet != url:
            logger.info(f"[lien court] deroule vers {complet}")
            return complet
    except Exception as e:
        logger.warning(f"[lien court] deroulage impossible : {e}")
    return url


def download_audio(url: str) -> str | None:
    """Download audio from URL using yt-dlp. Returns path to MP3 file."""
    url = derouler_lien_court(url)
    temp_dir = "/tmp"
    output_id = str(uuid.uuid4())
    output_template = f"{temp_dir}/{output_id}.%(ext)s"

    # Detect platform
    is_facebook = 'facebook.com' in url or 'fb.watch' in url or 'fb.com' in url
    is_instagram = 'instagram.com' in url
    is_tiktok = 'tiktok.com' in url or 'vm.tiktok.com' in url
    is_youtube = 'youtube.com' in url or 'youtu.be' in url

    ydl_opts = {
        'format': 'bestaudio/best[acodec!=none]/best',
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

    appliquer_reseau(ydl_opts)

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
        # Volontairement aucun User-Agent impose : yt-dlp imite un vrai
        # navigateur grace a curl_cffi (empreinte TLS + en-tetes coherents).
        # Ecrire un User-Agent d'iPhone par-dessus une empreinte de Chrome rend
        # la requete incoherente — exactement ce que TikTok sait detecter.
        pass

    elif is_youtube:
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }

    # TikTok peut refuser tout un lot d'adresses d'un pays donne tout en
    # acceptant celles d'un autre. Plutot que de parier sur un seul pays, on
    # essaie les pays configures l'un apres l'autre, avec une IP fixe par essai.
    tentatives: list[str | None] = [None]
    if is_tiktok and PROXY_URL and TIKTOK_COUNTRIES:
        tentatives = list(TIKTOK_COUNTRIES)

    try:
        derniere = None
        for numero, pays in enumerate(tentatives, start=1):
            if pays:
                ydl_opts['proxy'] = _proxy_cible(PROXY_URL, pays, f'tk{numero}')
                logger.info(f"[yt-dlp] TikTok essai {numero}/{len(tentatives)} via {pays}")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    logger.info(f"[yt-dlp] Downloading: {url}")
                    ydl.download([url])
                derniere = None
                break
            except Exception as e:
                derniere = e
                logger.error(f"[yt-dlp] essai {numero} echoue : {e}")
        if derniere is not None:
            raise derniere

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
        LAST_DOWNLOAD_ERROR['last'] = "Aucun fichier produit par yt-dlp"
        return None

    except Exception as e:
        logger.error(f"[yt-dlp] Error: {e}")
        LAST_DOWNLOAD_ERROR['last'] = f"{type(e).__name__}: {e}"
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
        os.path.join(FFMPEG_DIR, 'ffmpeg') if FFMPEG_DIR else None,
        '/var/www/pastefind-backend/bin/ffmpeg',
        '/usr/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        'ffmpeg'
    ]
    ffmpeg_paths = [p for p in ffmpeg_paths if p]

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
    # curl_cffi permet a yt-dlp d'imiter l'empreinte TLS d'un vrai navigateur.
    # Sans lui, TikTok repond « status code 0 ». Aucun secret ici, juste un etat.
    try:
        import curl_cffi
        imitation = "presente " + str(getattr(curl_cffi, '__version__', '?'))
    except Exception as e:
        imitation = f"absente ({type(e).__name__})"
    return {
        "status": "healthy",
        "version": "3.1",
        "audd_configured": bool(AUDD_API_TOKEN),
        "static_dir": STATIC_DIR,
        "html_exists": os.path.exists(HTML_FILE),
        "imitation_navigateur": imitation,
        "proxy": "oui" if PROXY_EFFECTIF else "non",
        "proxy_pays": PROXY_COUNTRY or "-",
        "session": "oui" if COOKIES_FILE else "non",
    }

@app.get("/diag")
async def diag(k: str = "", url: str = "", mode: str = ""):
    """Diagnostic TEMPORAIRE. Protege par une cle, a retirer une fois les liens repares."""
    if not DIAG_KEY or k != DIAG_KEY:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    import yt_dlp.version
    info = {"ytdlp": yt_dlp.version.__version__, "ffmpeg_dir": FFMPEG_DIR}
    ici = os.path.dirname(os.path.abspath(__file__))
    info["dossier_app"] = ici
    info["which"] = {"ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe")}
    info["proxy"] = "oui" if PROXY_EFFECTIF else "non"
    info["proxy_pays"] = PROXY_COUNTRY or "-"
    info["proxy_sessid"] = PROXY_SESSID or "-"
    # Etat des cookies : on ne rend JAMAIS les valeurs, seulement de quoi verifier.
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        try:
            lignes = [l for l in open(COOKIES_FILE, encoding='utf-8', errors='replace')
                      if l.strip() and not l.startswith('#')]
            domaines = {}
            for l in lignes:
                d = l.split('\t')[0].lstrip('.').lower()
                for cle in ('tiktok', 'instagram', 'facebook', 'youtube', 'google'):
                    if cle in d:
                        domaines[cle] = domaines.get(cle, 0) + 1
            info["cookies"] = {"lignes": len(lignes), "domaines": domaines}
        except Exception as e:
            info["cookies"] = f"illisible: {e}"
    else:
        info["cookies"] = "aucun"
    try:
        info["contenu_bin"] = sorted(os.listdir(os.path.join(ici, "bin")))[:20]
    except Exception as e:
        info["contenu_bin"] = f"illisible: {e}"
    if FFMPEG_DIR:
        for outil in ("ffmpeg", "ffprobe"):
            try:
                r = subprocess.run([os.path.join(FFMPEG_DIR, outil), "-version"],
                                   capture_output=True, text=True, timeout=15)
                info[outil] = (r.stdout or r.stderr).splitlines()[0][:120]
            except Exception as e:
                info[outil] = f"echec: {type(e).__name__}: {e}"
    if url and mode == "formats":
        info.update(await asyncio.to_thread(_diag_formats, url))
    elif url and mode == "brut":
        info.update(await asyncio.to_thread(_diag_brut, url))
    elif url:
        chemin = await asyncio.to_thread(download_audio, url)
        info["telechargement_ok"] = bool(chemin)
        info["erreur_yt_dlp"] = LAST_DOWNLOAD_ERROR.get("last", "")
        if chemin:
            info["taille"] = os.path.getsize(chemin)
            try:
                os.remove(chemin)
            except Exception:
                pass
    return info


def _diag_formats(url: str) -> dict:
    """Ce que yt-dlp voit sans rien telecharger."""
    opts = appliquer_reseau({'quiet': True, 'no_warnings': True,
                             'nocheckcertificate': True, 'skip_download': True})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            d = ydl.extract_info(url, download=False)
    except Exception as e:
        return {"formats_erreur": f"{type(e).__name__}: {str(e)[:300]}"}
    fmts = []
    for f in (d.get('formats') or [])[:40]:
        fmts.append({
            "id": f.get('format_id'), "ext": f.get('ext'),
            "acodec": f.get('acodec'), "vcodec": f.get('vcodec'),
            "abr": f.get('abr'), "taille": f.get('filesize') or f.get('filesize_approx'),
            "protocole": f.get('protocol'),
        })
    return {"titre": (d.get('title') or '')[:120], "duree": d.get('duration'),
            "id": d.get('id'), "page": d.get('webpage_url'),
            "extracteur": d.get('extractor'), "formats": fmts}


def _diag_brut(url: str) -> dict:
    """Telecharge SANS post-traitement, puis demande a ffprobe ce qu'il y a dedans."""
    ident = str(uuid.uuid4())
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'/tmp/{ident}.%(ext)s',
        'quiet': True, 'no_warnings': True, 'nocheckcertificate': True,
        'retries': 2,
    }
    appliquer_reseau(opts)
    res: dict = {}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        res["brut_erreur"] = f"{type(e).__name__}: {str(e)[:300]}"
    fichiers = [f for f in os.listdir('/tmp') if f.startswith(ident)]
    res["fichiers"] = fichiers
    for f in fichiers:
        p = f'/tmp/{f}'
        res["taille"] = os.path.getsize(p)
        try:
            with open(p, 'rb') as fh:
                res["debut_du_fichier"] = repr(fh.read(60))
        except Exception:
            pass
        if FFMPEG_DIR:
            try:
                r = subprocess.run(
                    [os.path.join(FFMPEG_DIR, 'ffprobe'), '-v', 'error', '-show_streams',
                     '-of', 'default=noprint_wrappers=1:nokey=0', p],
                    capture_output=True, text=True, timeout=30)
                res["ffprobe_sortie"] = (r.stdout or '')[:600]
                res["ffprobe_erreur"] = (r.stderr or '')[:300]
            except Exception as e:
                res["ffprobe_erreur"] = f"{type(e).__name__}: {e}"
        try:
            os.remove(p)
        except Exception:
            pass
    return res

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

        # Download audio. These are blocking (network + subprocess) calls —
        # run them in a worker thread so one slow download doesn't freeze the
        # event loop and every other visitor's request along with it.
        audio_path = await asyncio.to_thread(download_audio, url)

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
        audio_path = await asyncio.to_thread(truncate_audio_if_needed, audio_path)

        # Analyze
        result = await asyncio.to_thread(analyze_with_audd, audio_path)

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

        # Save to temp. Read in bounded chunks instead of file.read() in one
        # shot — an unbounded read lets anyone crash the server by posting a
        # multi-GB body (the 50 MB check in the browser is trivial to skip).
        temp_path = f"/tmp/{uuid.uuid4()}.{file_ext}"
        content = bytearray()
        chunk_size = 1024 * 1024
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_BYTES:
                return JSONResponse(status_code=413, content={
                    "error": "❌ Fichier trop volumineux (max 60 Mo).\n\n💡 Essayez de couper un extrait de 30 secondes."
                })
        content = bytes(content)

        if len(content) == 0:
            return JSONResponse(status_code=400, content={"error": "❌ Le fichier est vide."})

        with open(temp_path, "wb") as f_out:
            f_out.write(content)

        logger.info(f"[/api/upload] Saved: {temp_path} ({len(content)} bytes)")

        # Truncate if too large
        temp_path = await asyncio.to_thread(truncate_audio_if_needed, temp_path)

        # Analyze
        result = await asyncio.to_thread(analyze_with_audd, temp_path)

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
    <p><em>Dernière mise à jour : 22 août 2026</em></p>

    <h2>1. Introduction</h2>
    <p>PasteFind identifie un morceau de musique à partir d'un lien vidéo ou d'un fichier audio que vous fournissez. Cette politique décrit exactement quelles données sont traitées, pourquoi, et combien de temps elles sont conservées.</p>

    <h2>2. Données traitées</h2>
    <p>Selon ce que vous soumettez, PasteFind traite :</p>
    <ul>
        <li><strong>Le fichier audio ou vidéo que vous envoyez</strong>, ou l'enregistrement effectué depuis votre microphone si vous utilisez cette fonction.</li>
        <li><strong>L'adresse (URL) de la vidéo</strong> que vous collez, lorsque vous utilisez le mode « Lien Vidéo ». La vidéo correspondante est alors téléchargée temporairement pour en extraire l'audio.</li>
    </ul>
    <p>PasteFind ne demande pas de compte, ne collecte ni nom, ni adresse e-mail, ni donnée de localisation, et n'utilise ni cookie publicitaire ni traceur.</p>

    <h2>3. Utilisation et conservation</h2>
    <p>Seuls les 30 premières secondes de l'audio sont analysées. Cet extrait est transmis au service de reconnaissance musicale <a href="https://audd.io" target="_blank" rel="noopener">AudD.io</a>, qui l'utilise pour identifier le morceau et nous renvoyer son titre, son artiste et sa pochette. Le traitement d'AudD.io est régi par sa propre politique de confidentialité.</p>
    <p>Le fichier temporaire créé sur nos serveurs est <strong>supprimé immédiatement après l'analyse</strong>. Aucun historique de vos recherches n'est conservé, ni sur nos serveurs, ni sur votre appareil.</p>

    <h2>4. Vos droits</h2>
    <p>Puisqu'aucune donnée n'est conservée après l'analyse et qu'aucun compte n'est créé, il n'existe aucune donnée personnelle vous concernant à consulter, corriger ou supprimer. Pour toute question, vous pouvez nous écrire à l'adresse ci-dessous.</p>

    <h2>5. Contact</h2>
    <p>Email : <a href="mailto:contact@pastefind.com">contact@pastefind.com</a></p>
    <p>© 2026 PasteFind. Tous droits réservés.</p>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
