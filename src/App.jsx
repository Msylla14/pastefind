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

function App() {
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const handleAnalyze = async () => {
    if (!url) return
    setLoading(true)
    setError('')
    setResult(null)

    try {
      // Reverted to hit n8n directly not Python backend
      const response = await fetch('https://pastefind.com/api/analyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url }),
      })


      if (!response.ok) {
        throw new Error('Analysis request failed')
      }

      const data = await response.json()

      if (data.error) {
        setError('Erreur analyse: ' + data.error)
        return
      }

      setResult({
        title: data.title || 'Inconnu',
        artist: data.subtitle || 'Artiste inconnu',
        cover_url: data.image || null,
        youtube_url: data.youtube_url || '#',
        spotify_url: data.spotify_url || '#'
      })
    } catch (err) {
      console.error(err)
      setError('Erreur connexion serveur ou lien invalide.')
    } finally {
      setLoading(false)
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
        <input
          type="text"
          placeholder="Paste TikTok/YouTube link..."
          className="glass-input"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <button
          className="analyze-btn"
          onClick={handleAnalyze}
          disabled={loading}
        >
          {loading ? 'ANALYZING...' : 'ANALYZE'}
        </button>

        {error && <p className="error-text">{error}</p>}

        {result && (
          <div className="result-card">
            {result.cover_url && <img src={result.cover_url} alt="Cover" className="cover-art" />}
            <div className="song-info">
              <h3 translate="no" className="notranslate">{result.title}</h3>
              <p translate="no" className="notranslate">{result.artist}</p>
              <div className="action-buttons">
                <a href={result.youtube_url} target="_blank" rel="noopener noreferrer" className="icon-btn">
                  📺 YouTube
                </a>
                <a href={result.spotify_url} target="_blank" rel="noopener noreferrer" className="icon-btn">
                  🎵 Spotify
                </a>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default App
