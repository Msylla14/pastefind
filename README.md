# 🎵 PasteFind - Unified Architecture
**Version 2.0 (Stable)**

## Architecture Overview

PasteFind uses a unified architecture separating the frontend (GitHub Pages) and the backend (Render).

### 1. Frontend (GitHub Pages)
- **Role**: Serves the React Application (UI).
- **Build Tool**: Vite.
- **Output Directory**: `docs/` (Configured in `vite.config.js`).
- **URL**: `https://pastefind.com` (Mapped to GitHub Pages `docs/` folder via CNAME).
- **Features**:
  - **Mode Toggle**: Link vs File Upload.
  - **Microphone Button**: UI placeholder (Backend 501).
  - **Logic**: Calls `https://api.pastefind.com` for analysis.

### 2. Backend (Render)
- **Role**: JSON API ONLY (No HTML serving).
- **Framework**: FastAPI (Python).
- **URL**: `https://api.pastefind.com` (Mapped to Render Service).
- **Endpoints**:
  - `GET /` -> JSON Status & Version.
  - `GET /health` -> Health check.
  - `POST /api/analyze` -> Analyze YouTube/Facebook/TikTok links.
  - `POST /api/analyze-file` -> Analyze uploaded MP3/MP4/WAV files.
  - `POST /api/analyze-mic` -> Placeholder (Returns 501 Not Implemented).

## 🚀 Deployment Instructions

### Frontend (Update UI)
1. **Develop**: Edit `src/App.jsx`.
2. **Build**: Run `npm run build`. This outputs to the `docs/` folder.
3. **Deploy**:
   ```bash
   git add .
   git commit -m "Update Frontend"
   git push origin main
   ```
   *GitHub Pages is configured to serve from the `/docs` folder on the `main` branch.*

### Backend (Update Logic)
1. **Develop**: Edit `backend/main.py`.
2. **Deploy**:
   ```bash
   git add backend/
   git commit -m "Update Backend"
   git push origin main
   ```
   *Render automatically deploys changes to the `backend/` directory.*

## ⚠️ Important Notes
- **DO NOT** try to access the backend URL (`api.pastefind.com`) in a browser expecting to see the App. It only returns JSON.
- **YouTube Blocking**: YouTube links are blocked client-side to protect the server IP. Users must download the video and use "File Upload" mode.
