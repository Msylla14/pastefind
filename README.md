# 🎵 PasteFind

Reconnaissance musicale par lien vidéo ou fichier audio (type Shazam) : colle un lien TikTok/Facebook/Instagram, ou dépose un fichier audio, PasteFind identifie le titre et l'artiste via [AudD.io](https://audd.io) et renvoie les liens Spotify / Apple Music / YouTube.

## Architecture

Deux services indépendants.

### 1. Frontend — GitHub Pages
- **Fichier source réel : `index.html`** (page statique, JS vanilla — pas de composant React monté malgré la présence de `src/App.jsx`, voir note ci-dessous).
- **Build** : Vite, sortie dans `docs/` (voir `vite.config.js`).
- **URL** : `https://pastefind.com`.
- **Fonctionnalités** : lien vidéo ou fichier local, drag & drop, enregistrement micro (10s, auto-analysé via `/api/upload`), FR uniquement pour l'instant.
- Appelle `https://pastefind.onrender.com` pour l'analyse.

> ⚠️ **`src/App.jsx` et `src/main.jsx` ne sont pas utilisés en production.** `index.html` (à la racine) ne les charge pas — c'est une réécriture React/Three.js commencée mais jamais branchée. Pour modifier l'UI réellement en ligne, éditer `index.html`, pas `src/App.jsx`. Si vous reprenez la réécriture React un jour, il faudra remplacer `index.html` par un point d'entrée qui monte `src/main.jsx` (`<div id="root">` + `<script type="module" src="/src/main.jsx">`).

> ℹ️ Le site est aussi déployé sur Vercel (`pastfind.vercel.app`), branché sur le même dépôt. Les deux hébergeurs tournent aujourd'hui en parallèle — à trancher pour n'en garder qu'un.

### 2. Backend — Render (FastAPI)
- **Rôle** : API JSON uniquement.
- **URL en prod** : `https://pastefind.onrender.com` (le domaine `api.pastefind.com` mentionné dans une version antérieure de ce README n'est pas celui utilisé par le frontend — à aligner si ce sous-domaine doit remplacer l'URL Render brute).
- **Endpoints** :
  - `GET /health` → statut, indique si `AUDD_API_TOKEN` est configuré.
  - `POST /api/analyze` → analyse un lien vidéo (`{ "url": "..." }`).
  - `POST /api/upload` → analyse un fichier uploadé (`multipart/form-data`, champ `file`).
  - `POST /api/analyze-mic` → placeholder (501), non utilisé par le frontend actuel (le micro passe par `/api/upload`).
- **Variable d'environnement requise** : `AUDD_API_TOKEN` (clé AudD.io).

## 🚀 Déploiement

### Frontend
1. Éditer `index.html` (ou `src/` si la réécriture React est reprise — voir note ci-dessus).
2. `npm run build` → régénère `docs/`.
3. `git add . && git commit -m "..." && git push origin main`
   *GitHub Pages sert `/docs` sur `main`.*

### Backend
1. Éditer `backend/main.py`.
2. `git add backend/ && git commit -m "..." && git push origin main`
   *Render redéploie automatiquement `backend/`.*

## ⚠️ Notes importantes
- L'URL backend ne sert que du JSON — ne pas l'ouvrir dans un navigateur en attendant l'app.
- YouTube est bloqué côté client (protection de l'IP serveur) : l'utilisateur doit télécharger la vidéo puis utiliser "Fichier Local".
- Taille de fichier acceptée : 50 Mo côté client, 60 Mo en dur côté serveur.

## 💰 Services payants — à surveiller

Le site dépend de deux abonnements. **Si l'un des deux lapse, le site s'arrête.** C'est exactement ce qui est arrivé entre mai et août 2026 : facture Render impayée → service suspendu, puis abonnement AudD expiré → reconnaissance impossible.

| Service | Rôle | Ordre de grandeur | Si ça lapse |
|---|---|---|---|
| **Render** | héberge le backend | ~6-7 $/mois | Le serveur est suspendu, le site affiche l'interface mais aucune analyse n'aboutit. |
| **AudD.io** | reconnaît la musique | forfait Indie 5 $/mois (1000 requêtes) | L'API renvoie `authorization failed`, aucune musique n'est identifiée. |

Vérifier périodiquement que la carte enregistrée est valide chez les deux. `GET /health` indique si une clé AudD est présente (`audd_configured`), mais **pas** si l'abonnement est actif — seul un vrai test d'analyse le confirme.
