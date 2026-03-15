"""
FastAPI server for PhysiHow: exercise catalog (Uni Melbourne CHESM / data/exercises.json) + Gemini coach.
Run from repo root: uvicorn api.main:app --reload --port 8000

Env: GEMINI_API_KEY (required for coach). Exercises loaded from data/exercises.json.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv
    load_dotenv(repo_root / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

EXERCISES_JSON = Path(os.environ.get("PHYSIHOW_EXERCISES_JSON", str(repo_root / "data" / "exercises.json")))

app = FastAPI(title="PhysiHow", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_exercises_list: list[dict] = []
_exercises_by_slug: dict[str, dict] = {}
_exercise_source: str = "local"


def load_exercises() -> tuple[list[dict], dict[str, dict]]:
    """Load exercises from data/exercises.json (Uni Melbourne CHESM knee/hip OA library)."""
    global _exercises_list, _exercises_by_slug
    if _exercises_by_slug:
        return _exercises_list, _exercises_by_slug
    exercises: list[dict] = []
    if EXERCISES_JSON.is_file():
        with open(EXERCISES_JSON, encoding="utf-8") as f:
            data = json.load(f)
        exercises = data.get("exercises", [])
    _exercises_list = exercises
    _exercises_by_slug = {}
    for ex in exercises:
        slug = ex.get("slug") or (str(ex.get("id", "")) if ex.get("id") is not None else "")
        if slug:
            _exercises_by_slug[slug] = ex
    return _exercises_list, _exercises_by_slug


@app.get("/api/health")
def health():
    """Ok if GEMINI_API_KEY is set and we have exercises from data/exercises.json."""
    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY or GOOGLE_API_KEY not set")
    list_, _ = load_exercises()
    if not list_ and not EXERCISES_JSON.is_file():
        raise HTTPException(
            status_code=503,
            detail="No exercises. Add data/exercises.json",
        )
    return {"status": "ok", "exercise_source": _exercise_source}


@app.get("/api/exercises")
def list_exercises():
    """Return list of exercises: slug, name, url."""
    list_, _ = load_exercises()
    return {
        "exercises": [
            {
                "slug": ex.get("slug") or str(ex.get("id", "")),
                "name": ex.get("name") or ex.get("exerciseName", ""),
                "url": ex.get("url") or ex.get("sourceExerciseUrl", ""),
            }
            for ex in list_
        ]
    }


@app.get("/api/exercises/{slug}")
def get_exercise(slug: str):
    """Return full exercise details by slug (for coach context)."""
    _, by_slug = load_exercises()
    ex = by_slug.get(slug)
    if not ex:
        raise HTTPException(status_code=404, detail=f"Exercise {slug!r} not found")
    slug_val = ex.get("slug") or str(ex.get("id", ""))
    name_val = ex.get("name") or ex.get("exerciseName", "")
    url_val = ex.get("url") or ex.get("sourceExerciseUrl", "")
    full_text = (ex.get("fullText") or ex.get("description") or "").strip()
    return {
        "slug": slug_val,
        "name": name_val,
        "url": url_val,
        "technique": ex.get("technique", ""),
        "targetMuscles": ex.get("targetMuscles", ""),
        "introduction": ex.get("introduction", ""),
        "fullText": full_text,
    }


class ChatTurn(BaseModel):
    role: str  # "user" | "model"
    text: str


class CoachChatRequest(BaseModel):
    exercise_slug: str
    message: str
    history: list[ChatTurn] = []


class CoachChatResponse(BaseModel):
    reply: str


@app.post("/api/coach/chat", response_model=CoachChatResponse)
def coach_chat(request: CoachChatRequest):
    """Text chat with the coach (Gemini generateContent). Back-and-forth with history."""
    try:
        from api.coach_chat import chat
        history_dicts = [{"role": t.role, "text": t.text} for t in request.history]
        reply = chat(request.exercise_slug, request.message, history_dicts)
        return CoachChatResponse(reply=reply)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.exception("Coach chat error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


class SuggestRequest(BaseModel):
    exercise_slug: str
    concern: str


class CompileSessionRequest(BaseModel):
    exercise_name: str
    transcript: str
    user_notes: str


@app.post("/api/suggest-exercise")
async def suggest_exercise(req: SuggestRequest):
    """Railtracks agent: suggest alternative exercises given a concern."""
    try:
        from api.agents import suggest_agent
        import railtracks as rt
        prompt = (
            f"Current exercise slug: {req.exercise_slug}\n"
            f"User concern: {req.concern}"
        )
        result = await rt.call(suggest_agent, prompt)
        return {"suggestions": result.text}
    except Exception as e:
        logging.exception("suggest-exercise error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/compile-session")
async def compile_session(req: CompileSessionRequest):
    """Railtracks agent: compile session transcript into structured markdown notes."""
    try:
        from api.agents import notes_agent
        import railtracks as rt
        today = datetime.date.today().isoformat()
        prompt = (
            f"Date: {today}\n"
            f"Exercise: {req.exercise_name}\n\n"
            f"Session transcript:\n{req.transcript}\n\n"
            f"Additional user notes:\n{req.user_notes or '(none)'}"
        )
        result = await rt.call(notes_agent, prompt)
        return {"markdown": result.text}
    except Exception as e:
        logging.exception("compile-session error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/api/coach")
async def coach_websocket(websocket: WebSocket):
    """Gemini Live coach session. Client sends exercise_slug on connect, then audio/video/text."""
    await websocket.accept()
    try:
        from api.coach_live import run_coach_session
        await run_coach_session(websocket)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logging.exception("Coach WebSocket error: %s", e)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
        await websocket.close(code=1011)
