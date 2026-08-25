# 🎵 PasteFind

Reconnaissance musicale par lien vidéo ou fichier audio (type Shazam) : colle un lien
TikTok / Facebook / Instagram, dépose un fichier audio, ou laisse le micro écouter.
PasteFind identifie le titre et l'artiste via AudD.io et renvoie les liens
Spotify / Apple Music / YouTube.

Site : <https://pastefind.com>

---

## Architecture

Deux services indépendants.

### 1. Frontend — GitHub Pages

| | |
|---|---|
| Fichier servi en production | **`index.html` à la racine du dépôt** |
| Workflow | `.github/workflows/static.yml` |
| Contenu publié | **la racine du dépôt (`path: '.'`)**, pas `docs/` |
| URL | <https://pastefind.com> |

> ⚠️ **Le site est servi depuis la RACINE du dépôt, pas depuis `docs/`.**
> Une ancienne version de ce README affirmait le contraire — c'était faux, et
> ça fait perdre du temps. Vérification rapide : un fichier commité dans `docs/`
> est accessible à `pastefind.com/docs/<fichier>`, jamais à `pastefind.com/<fichier>`.
> Donc **toute modification du site en ligne se fait sur les fichiers à la racine.**

Fichiers du site, tous à la racine :

```
index.html                 la page complète (HTML + CSS + JS en un seul fichier)
manifest.webmanifest       rend l'app installable (PWA)
sw.js                      service worker (coquille hors ligne ; /api/ jamais mis en cache)
favicon.png                onglet du navigateur
icon-192.png               icône app 192×192
icon-512.png               icône app 512×512
icon-maskable-512.png      icône adaptative Android
privacy/index.html         politique de confidentialité (exigée par Google Play)
```

Fonctionnalités : lien vidéo, fichier local (drag & drop), micro (10 s, envoyé à
`/api/upload`), historique local des trouvailles (localStorage, jamais envoyé au
serveur), copie et partage du titre. Français uniquement pour l'instant.

Dossiers **non servis / non utilisés** : `docs/`, `dist/`, `public/`, `src/`.
`src/App.jsx` est une réécriture React commencée puis abandonnée : elle n'est
chargée par rien. Ne pas la modifier en croyant modifier le site.

ℹ️ Le dépôt est aussi branché sur Vercel (`pastfind.vercel.app`). Les deux
hébergeurs tournent en parallèle — à trancher pour n'en garder qu'un.

### 2. Backend — Render (FastAPI)

API JSON uniquement : <https://pastefind.onrender.com>

| Endpoint | Rôle |
|---|---|
| `GET /health` | statut ; indique si `AUDD_API_TOKEN` est configuré |
| `POST /api/analyze` | analyse un lien vidéo — `{"url": "..."}` |
| `POST /api/upload` | analyse un fichier — `multipart/form-data`, champ `file` |
| `POST /api/analyze-mic` | placeholder (501), non utilisé — le micro passe par `/api/upload` |

Variable d'environnement requise : `AUDD_API_TOKEN`.

---

## 🚀 Déploiement

### Frontend

1. Modifier les fichiers **à la racine** (`index.html`, `sw.js`, `manifest.webmanifest`…).
2. Commiter sur `main` — le workflow republie automatiquement en ~30 s.

Ne pas lancer `npm run build` : la sortie va dans `docs/`, qui n'est plus servi.

### Backend

1. Modifier `backend/main.py`.
2. Commiter sur `main` — Render redéploie automatiquement.

---

## ⚠️ Notes importantes

- L'URL du backend ne sert que du JSON — ne pas l'ouvrir dans un navigateur en
  attendant de voir l'application.
- YouTube est bloqué côté serveur (détection de robot sur les IP de datacenter) :
  l'utilisateur doit télécharger la vidéo puis passer par l'onglet **Fichier**.
- Taille de fichier acceptée : 50 Mo côté client, 60 Mo en dur côté serveur.

---

## 💰 Services payants — à surveiller

Le site dépend de deux abonnements. Si l'un des deux lapse, le site s'arrête.
C'est exactement ce qui est arrivé entre mai et août 2026 : facture Render
impayée → service suspendu, puis abonnement AudD expiré → reconnaissance impossible.

| Service | Rôle | Ordre de grandeur | Si ça lapse |
|---|---|---|---|
| **Render** | héberge le backend | ~6–7 $/mois | Le serveur est suspendu : l'interface s'affiche, aucune analyse n'aboutit. |
| **AudD.io** | reconnaît la musique | forfait Indie 5 $/mois (1000 requêtes) | L'API renvoie `authorization failed`, aucune musique identifiée. |

Vérifier périodiquement que la carte enregistrée est valide chez les deux.
`GET /health` indique si une clé AudD est présente (`audd_configured`), mais pas
si l'abonnement est actif — seul un vrai test d'analyse le confirme.
