# PasteFind

## How to Run

### Frontend (The 3D Interface)
1. Open a terminal.
2. Run `npm install` (only needed once).
3. Run `npm run dev`.
4. Open [http://localhost:5173](http://localhost:5173).

### Backend (The API)
1. Open a new terminal.
2. Run `pip install -r requirements.txt` (only needed once).
3. Run `uvicorn backend.main:app --reload`.
4. The API will be available at [http://localhost:8000](http://localhost:8000).

## Project Structure
- `src/`: React Frontend code.
- `backend/`: FastAPI Backend code.

---
Original Vite Readme below:

# PasteFind

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.
