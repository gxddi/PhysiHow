"""
Railtracks agentic workers for PhysiHow.
- suggest_agent: reads exercises.json, suggests alternatives given a concern.
- notes_agent:   compiles a session transcript into a structured .md report.
"""
from __future__ import annotations

import json
from pathlib import Path

import railtracks as rt

_EXERCISES_JSON = Path(__file__).resolve().parents[1] / "data" / "exercises.json"


@rt.function_node
def get_exercises() -> list[dict]:
    """Return name, slug, and introduction for every available exercise."""
    with open(_EXERCISES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return [
        {
            "slug": ex.get("slug") or str(ex.get("id", "")),
            "name": ex.get("name") or ex.get("exerciseName", ""),
            "intro": (ex.get("introduction") or ex.get("description") or "")[:300],
        }
        for ex in data.get("exercises", [])
    ]


suggest_agent = rt.agent_node(
    "ExerciseSuggester",
    llm=rt.llm.GeminiLLM("gemini-2.5-flash"),
    tool_nodes=[get_exercises],
    system_message=(
        "You are a physiotherapy assistant. "
        "The user is doing an exercise and has raised a concern (pain, difficulty, boredom, etc.). "
        "Call get_exercises to fetch the full list, then suggest 2–3 suitable alternatives. "
        "For each suggestion include: name, why it suits the concern, and the source slug. "
        "Be concise — one short paragraph per suggestion."
    ),
)

notes_agent = rt.agent_node(
    "SessionNotesCompiler",
    llm=rt.llm.GeminiLLM("gemini-2.5-flash"),
    system_message=(
        "You compile physiotherapy session notes into a structured markdown document. "
        "Use these headings: Date, Exercise, Session Summary, Form Observations, "
        "Reps / Sets (if mentioned), Coach Feedback, Recommended Next Steps. "
        "Today's date is available in the prompt. Be concise and clinically useful. "
        "Output only the markdown — no preamble."
    ),
)
