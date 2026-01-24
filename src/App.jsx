import React, { Suspense, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Sphere, MeshDistortMaterial } from '@react-three/drei'
import './App.css'

function AnimatedSphere() {
  return (
    <Sphere visible args={[1, 100, 200]} scale={2.5}>
      <MeshDistortMaterial
        color="#8352FD"
        attach="material"
        distort={0.4}
        speed={1.5}
        roughness={0.2}
      />
    </Sphere>
  )
}

// --- I18n Configuration ---
const TRANSLATIONS = {
  fr: {
    placeholder: "Collez un lien Facebook/TikTok...",
    upload_title: "GLISSEZ VOTRE FICHIER ICI",
    upload_subtitle: "ou cliquez pour parcourir (MP3, MP4)",
    analyze_btn: "ANALYSER",
    analyzing: "ANALYSE EN COURS...",
    error_server: "Erreur connexion serveur. Veuillez réessayer.",
    youtube_error: "YouTube bloque l'extraction directe. Téléchargez la vidéo et utilisez l'Upload Local.",
    title_unknown: "Inconnu",
    artist_unknown: "Artiste inconnu",
    invalid_link: "Lien invalide. Veuillez entrer une URL correcte."
  },
  en: {
    placeholder: "Paste Facebook/TikTok link...",
    upload_title: "DROP FILE HERE",
    upload_subtitle: "or click to browse (MP3, MP4)",
    analyze_btn: "ANALYZE",
    analyzing: "ANALYZING...",
    error_server: "Server connection error. Please try again.",
    youtube_error: "YouTube blocks direct extraction. Download video and use Local Upload.",
    title_unknown: "Unknown",
    artist_unknown: "Unknown Artist",
    invalid_link: "Invalid link. Please enter a correct URL."
  }
}

// Default Vinyl Cover (Stylized SVG Data URI)
const DEFAULT_COVER = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500"><defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" style="stop-color:%23333;stop-opacity:1" /><stop offset="100%" style="stop-color:%23000;stop-opacity:1" /></linearGradient></defs><circle cx="250" cy="250" r="240" fill="url(%23g)" stroke="%23555" stroke-width="5"/><circle cx="250" cy="250" r="100" fill="%238352FD"/><circle cx="250" cy="250" r="10" fill="%23fff"/><path d="M 250 250 m -90, 0 a 90,90 0 1,0 180,0 a 90,90 0 1,0 -180,0" fill="none" stroke="rgba(255,255,255,0.2)" stroke-width="2"/><path d="M 250 250 m -160, 0 a 160,160 0 1,0 320,0 a 160,160 0 1,0 -320,0" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="2"/></svg>`;

// Simple Auto-Detect
const lang = navigator.language.startsWith('fr') ? 'fr' : 'en'
const t = TRANSLATIONS[lang]

function App() {
  const [mode, setMode] = useState('link') // 'link' or 'upload'

  const handleAnalyze = async () => {
    setLoading(true)
    setError('')
    setResult(null)

    try {
      let response;

      // LOGIC: File Upload vs URL
      if (mode === 'upload') {
        if (!file) {
          setError(t.upload_title) // Reuse text or add specific error
          setLoading(false)
          return
        }
        const formData = new FormData()
        formData.append('file', file)

        response = await fetch('https://pastefind.onrender.com/api/analyze-file', {
          method: 'POST',
          body: formData
        })
      } else {
        if (!url) {
          setLoading(false)
          return
        }
        // Validate URL
        const urlPattern = /^(https?:\/\/)?([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$/
        if (!urlPattern.test(url)) {
          setError(t.invalid_link)
          setLoading(false)
          return
        }

        // Frontend YouTube Block
        if (url.includes('youtube.com') || url.includes('youtu.be')) {
          setError(t.youtube_error)
          setLoading(false)
          return
        }

        response = await fetch('https://pastefind.onrender.com/api/analyze', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ url }),
        })
      }

      if (!response.ok) {
        throw new Error('Request failed')
      }

      const data = await response.json()

      if (data.error) {
        setError(data.error)
        return
      }

      setResult({
        title: data.title || t.title_unknown,
        artist: data.subtitle || t.artist_unknown,
        cover_url: data.image || DEFAULT_COVER,
        youtube_url: data.youtube_url || '#',
        spotify_url: data.spotify_url || '#'
      })
    } catch (err) {
      console.error(err)
      setError(t.error_server)
    } finally {
      setLoading(false)
      // Reset file input if needed
    }
  }

  const handleFileChange = (e) => {
    if (e.target.files[0]) {
      setFile(e.target.files[0])
    }
  }

  return (
    <div className="app-container">
      <div className="canvas-container">
        <Canvas>
          <Suspense fallback={null}>
            <ambientLight intensity={0.5} />
            <pointLight position={[10, 10, 10]} />
            <AnimatedSphere />
            <OrbitControls enableZoom={false} />
          </Suspense>
        </Canvas>
      </div>

      <div className="overlay-container">

        {/* MODE TOGGLE */}
        <div className="mode-switch">
          <button
            className={`mode-btn ${mode === 'link' ? 'active' : ''}`}
            onClick={() => setMode('link')}
          >
            🔗 Lien Vidéo
          </button>
          <button
            className={`mode-btn ${mode === 'upload' ? 'active' : ''}`}
            onClick={() => {
              setMode('upload')
              setResult(null)
              setError('')
            }}
          >
            📂 Fichier Local
          </button>
        </div>

        {/* 1. URL Input Mode */}
        {mode === 'link' && (
          <input
            type="text"
            placeholder={t.placeholder}
            className="glass-input"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        )}

        {/* 2. Upload Mode */}
        {mode === 'upload' && (
          <div className="upload-wrapper">
            <div className={`upload-zone ${file ? 'has-file' : ''}`}>
              <input
                type="file"
                accept=".mp3,.wav,.mp4,.m4a"
                onChange={handleFileChange}
                className="upload-input-hidden"
              />
              <div className="upload-icon-large">
                {file ? '✅' : '☁️'}
              </div>
              {file ? (
                <div className="file-name-display">{file.name}</div>
              ) : (
                <>
                  <div className="upload-text">{t.upload_title}</div>
                  <div className="upload-subtext">{t.upload_subtitle}</div>
                </>
              )}
            </div>
          </div>
        )}

        <div className="button-group" style={{ display: 'flex', gap: '10px', marginTop: '20px', width: '100%' }}>
          <button
            className="analyze-btn"
            onClick={handleAnalyze}
            disabled={loading || (mode === 'link' && !url) || (mode === 'upload' && !file)}
            style={{ flex: 1, padding: '18px' }}
          >
            {loading ? t.analyzing : t.analyze_btn}
          </button>

          <button
            className="mic-btn"
            onClick={() => alert("Microphone soon!")}
            title="Listen (Soon)"
            style={{
              padding: '18px',
              borderRadius: '50px',
              border: 'none',
              background: 'rgba(255,255,255,0.1)',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '1.5rem'
            }}
          >
            🎙️
          </button>
        </div>

        {error && (
          <div className="error-box" style={{
            background: 'rgba(255,0,0,0.2)',
            padding: '15px',
            borderRadius: '12px',
            marginTop: '10px',
            border: '1px solid rgba(255,100,100,0.5)',
            width: '100%'
          }}>
            <p className="error-text">{error}</p>
          </div>
        )}

        {result && (
          <div className="result-card">
            <img
              src={result.cover_url}
              alt="Cover"
              className="cover-art"
              onError={(e) => { e.target.src = DEFAULT_COVER }}
            />
            <div className="song-info">
              <h3 translate="no" className="notranslate">{result.title}</h3>
              <p translate="no" className="notranslate">{result.artist}</p>
              <div className="action-buttons">
                {result.youtube_url && result.youtube_url !== '#' && (
                  <a href={result.youtube_url} target="_blank" rel="noopener noreferrer" className="icon-btn">
                    📺 YouTube
                  </a>
                )}
                {result.spotify_url && result.spotify_url !== '#' && (
                  <a href={result.spotify_url} target="_blank" rel="noopener noreferrer" className="icon-btn">
                    🎵 Spotify
                  </a>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
export default App
