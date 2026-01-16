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
    or_mic: "OU MICROPHONE",
    analyze_btn: "ANALYSER",
    analyzing: "ANALYSE EN COURS...",
    recording: "ENREGISTREMENT... (10s max)",
    error_server: "Erreur connexion serveur. Veuillez réessayer.",
    error_mic: "Erreur micro. Vérifiez les permissions.",
    youtube_hint: "ℹ️ Astuce : Téléchargez la vidéo avec un outil externe et uploadez le fichier ici.",
    title_unknown: "Inconnu",
    artist_unknown: "Artiste inconnu",
    invalid_link: "Lien invalide. Veuillez entrer une URL correcte."
  },
  en: {
    placeholder: "Paste Facebook/TikTok link...",
    or_upload: "OR UPLOAD A FILE (MP3/MP4)",
    or_mic: "OR MICROPHONE",
    analyze_btn: "ANALYZE",
    analyzing: "ANALYZING...",
    recording: "RECORDING... (10s max)",
    error_server: "Server connection error. Please try again.",
    error_mic: "Microphone error. Check permissions.",
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
  const [recording, setRecording] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [file, setFile] = useState(null)

  // Microphone Logic
  const startRecording = async () => {
    setError('')
    setResult(null)
    setUrl('')
    setFile(null)

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      const chunks = []

      mediaRecorder.ondataavailable = (e) => chunks.push(e.data)

      mediaRecorder.onstop = async () => {
        const blob = new Blob(chunks, { type: 'audio/webm' })
        await handleMicAnalyze(blob)

        // Stop all tracks
        stream.getTracks().forEach(track => track.stop())
      }

      mediaRecorder.start()
      setRecording(true)

      // Auto-stop after 8 seconds
      setTimeout(() => {
        if (mediaRecorder.state === 'recording') {
          mediaRecorder.stop()
          setRecording(false)
        }
      }, 8000)

    } catch (err) {
      console.error("Mic Error:", err)
      setError(t.error_mic)
    }
  }

  const handleMicAnalyze = async (audioBlob) => {
    setLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', audioBlob, 'recording.webm')

      const response = await fetch('https://pastefind.onrender.com/api/analyze-mic', {
        method: 'POST',
        body: formData
      })

      if (!response.ok) throw new Error('Mic Analysis Failed')

      const data = await response.json()
      if (data.error) {
        setError(data.error)
      } else {
        setResult({
          title: data.title || t.title_unknown,
          artist: data.subtitle || t.artist_unknown,
          cover_url: data.image || 'https://via.placeholder.com/300x300?text=No+Cover',
          youtube_url: data.youtube_url || '#',
          spotify_url: data.spotify_url || '#'
        })
      }
    } catch (err) {
      console.error(err)
      setError(t.error_server)
    } finally {
      setLoading(false)
    }
  }

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
            disabled={!!file || recording}
          />

          <div className="actions-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '10px' }}>
            <div className="file-upload-wrapper" style={{ flex: 1 }}>
              <p style={{ margin: '5px 0', fontSize: '0.8em', opacity: 0.8 }}>{t.or_upload}</p>
              <input
                type="file"
                accept=".mp3,.wav,.mp4,.m4a"
                onChange={handleFileChange}
                className="file-input"
                style={{ color: 'white' }}
                disabled={recording}
              />
            </div>

            {/* Micro Button */}
            <button
              className={`mic-btn ${recording ? 'recording' : ''}`}
              onClick={startRecording}
              disabled={loading || recording}
              title="Listen (Microphone)"
              style={{
                background: 'rgba(0,0,0,0.5)',
                border: '2px solid #39ff14', // Neon Green
                borderRadius: '50%',
                width: '50px',
                height: '50px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginLeft: '15px',
                boxShadow: recording ? '0 0 15px #39ff14' : 'none',
                transition: 'all 0.3s ease'
              }}
            >
              {/* Simple Mic SVG Icon */}
              <svg viewBox="0 0 24 24" fill="#39ff14" width="24px" height="24px">
                <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.66 9 5v6c0 1.66 1.34 3 3 3z" />
                <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
              </svg>
            </button>
          </div>
        </div>

        <button
          className="analyze-btn"
          onClick={handleAnalyze}
          disabled={loading || recording || (!url && !file)}
          style={{ marginTop: '15px' }}
        >
          {loading ? t.analyzing : (recording ? t.recording : t.analyze_btn)}
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
