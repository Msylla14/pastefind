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
    or_upload: "OU UPLOADEZ UN FICHIER (MP3/MP4)",
    analyze_btn: "ANALYSER",
    analyzing: "ANALYSE EN COURS...",
    error_server: "Erreur connexion serveur. Veuillez réessayer.",
    youtube_hint: "ℹ️ Astuce : Téléchargez la vidéo avec un outil externe et uploadez le fichier ici.",
    title_unknown: "Inconnu",
    artist_unknown: "Artiste inconnu",
    invalid_link: "Lien invalide. Veuillez entrer une URL correcte."
  },
  en: {
    placeholder: "Paste Facebook/TikTok link...",
    or_upload: "OR UPLOAD A FILE (MP3/MP4)",
    analyze_btn: "ANALYZE",
    analyzing: "ANALYZING...",
    error_server: "Server connection error. Please try again.",
    youtube_hint: "ℹ️ Hint: Download the video externally and upload the file here.",
    title_unknown: "Unknown",
    artist_unknown: "Unknown Artist",
    invalid_link: "Invalid link. Please enter a correct URL."
  }
}

// Simple Auto-Detect
const lang = navigator.language.startsWith('fr') ? 'fr' : 'en'
const t = TRANSLATIONS[lang]

function App() {
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [file, setFile] = useState(null)

  const handleAnalyze = async () => {
    setLoading(true)
    setError('')
    setResult(null)

    try {
      let response;

      // LOGIC: File Upload vs URL
      if (file) {
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
          setError("YouTube est bloqué côté serveur. Veuillez utiliser l’upload de fichier.")
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
        cover_url: data.image || 'https://via.placeholder.com/300x300?text=No+Cover',
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
      setUrl('')
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
        {/* Upload Mode Switcher or Simple Dual Input */}
        <div className="input-group">
          <input
            type="text"
            placeholder={t.placeholder}
            className="glass-input"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value)
              setFile(null)
            }}
            disabled={!!file}
          />

          <div className="file-upload-wrapper" style={{ marginTop: '10px' }}>
            <p style={{ margin: '5px 0', fontSize: '0.8em', opacity: 0.8 }}>{t.or_upload}</p>
            <input
              type="file"
              accept=".mp3,.wav,.mp4,.m4a"
              onChange={handleFileChange}
              className="file-input"
              style={{ color: 'white' }}
            />
          </div>
        </div>

        <button
          className="analyze-btn"
          onClick={handleAnalyze}
          disabled={loading || (!url && !file)}
          style={{ marginTop: '15px' }}
        >
          {loading ? t.analyzing : t.analyze_btn}
        </button>

        {error && (
          <div className="error-box" style={{
            background: 'rgba(255,0,0,0.2)',
            padding: '10px',
            borderRadius: '8px',
            marginTop: '10px',
            border: '1px solid rgba(255,100,100,0.5)'
          }}>
            <p className="error-text">{error}</p>
            {/* Suggest File Upload if YouTube error */}
            {error.includes("YouTube") && (
              <p style={{ fontSize: '0.8em', marginTop: '5px' }}>
                {t.youtube_hint}
              </p>
            )}
          </div>
        )}

        {result && (
          <div className="result-card">
            <img
              src={result.cover_url}
              alt="Cover"
              className="cover-art"
              onError={(e) => { e.target.src = 'https://via.placeholder.com/300x300?text=No+Cover' }}
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
