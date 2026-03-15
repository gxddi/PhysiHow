"""
Text chat with the coach using Gemini generateContent (AI Studio–style).
No Live/WebSocket; simple request/response with conversation history.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXERCISES_JSON = Path(
    os.environ.get("PHYSIHOW_EXERCISES_JSON", str(_REPO_ROOT / "data" / "exercises.json"))
)


def _get_genai():
    try:
        from google import genai
        from google.genai import types
        return genai, types
    except ImportError as e:
        raise RuntimeError("google-genai required. Install with: pip install google-genai") from e


def _load_exercise_by_slug(slug: str) -> dict | None:
    if not _EXERCISES_JSON.is_file():
        return None
    try:
        with open(_EXERCISES_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Could not load exercises: %s", e)
        return None
    for ex in data.get("exercises", []):
        if (ex.get("slug") or ex.get("id", "")) == slug:
            return ex
    return None


def _validate_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for t in history:
        role = (t.get("role") or "user").lower()
        if role not in ("user", "model"):
            role = "user"
        text = (t.get("text") or "").strip()
        if text:
            out.append({"role": role, "text": text})
    return out


def _build_system_instruction(exercise: dict | None) -> str:
    if not exercise:
        return """You are a physiotherapy exercise coach. The user has not selected an exercise yet.
Suggest they pick an exercise from the app to get started. Be brief and friendly."""

    name = exercise.get("name") or exercise.get("exerciseName", "")
    url = exercise.get("url") or exercise.get("sourceExerciseUrl", "")
    full_text = (exercise.get("fullText") or exercise.get("description") or "").strip() or (
        (exercise.get("introduction") or "")
        + "\n\n"
        + (exercise.get("technique") or "")
        + "\n\n"
        + (exercise.get("targetMuscles") or "")
    )
    return f"""You are a physiotherapy exercise coach guiding the user through: {name}.

Here is the exercise information (from University of Melbourne CHESM knee/hip OA video library):
---
{full_text}
---
Source: {url}

Your job:
- Guide the user step by step through performing this exercise.
- Answer questions about the exercise, technique, and form.
- Be encouraging, specific, and concise.
- Reply in plain text; no markdown. Keep responses focused and conversational."""


def chat(exercise_slug: str, message: str, history: list[dict[str, str]]) -> str:
    """
    Send user message with conversation history; return model reply.
    history: list of { "role": "user" | "model", "text": "..." }
    """
    genai, types = _get_genai()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not set")

    exercise = _load_exercise_by_slug(exercise_slug) if exercise_slug else None
    system_text = _build_system_instruction(exercise)
    history = _validate_history(history or [])

    # Build contents: alternating user/model from history, then new user message
    contents: list[Any] = []
    for turn in history:
        role = turn.get("role", "user")
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        if role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
        else:
            contents.append(types.Content(role="model", parts=[types.Part(text=text)]))
    message = (message or "").strip()
    if not message:
        raise ValueError("message is required")
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

    model_id = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=model_id,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_text,
        ),
    )

    if not response or not response.candidates:
        raise RuntimeError("No response from model")

    candidate = response.candidates[0]
    if not candidate.content or not candidate.content.parts:
        raise RuntimeError("Empty model reply")

    text = candidate.content.parts[0].text
    return (text or "").strip()
