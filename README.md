# PhysiHow

Pick a physiotherapy exercise from the **University of Melbourne CHESM video library** (knee and hip osteoarthritis), open camera + chat, and get live guidance from an AI coach (Gemini Live). No exercise detection — you choose the exercise; the coach guides you. Targeted at elderly people with knee and/or hip OA.

**→ Features and requirements: [docs/FEATURES.md](docs/FEATURES.md).**

## Quick start (from repo root)

```bash
# 1. Backend
pip install -r requirements-api.txt
# Set GEMINI_API_KEY in a .env file (copy .env.example)
uvicorn api.main:app --reload --port 8000
# Or: npm run api   (with venv activated), or  scripts\run_api.bat

# 2. Frontend (other terminal)
npm i && npm run dev
```

Open **https://localhost:5173** → pick an exercise → Start → camera + coach session.

## Exercise catalog

Exercises are loaded from **`data/exercises.json`**, which contains the [University of Melbourne CHESM](https://healthsciences.unimelb.edu.au/departments/physiotherapy/chesm/video-library/exercise) knee and hip osteoarthritis set (e.g. seated knee extension, sit to stand, step ups, partial wall squats). “View in video library” in the app links to that page.

## Layout

| Path | Purpose |
|------|---------|
| `api/` | FastAPI: `/api/exercises`, `/api/exercises/{slug}`, `/api/coach` (WS), `/api/health` |
| `src/` | Frontend: exercise picker + camera + coach chat (multimodal) |
| `data/` | exercises.json (CHESM exercise list and coach context) |
