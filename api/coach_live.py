"""
Gemini Live coach: WebSocket handler. Multimodal messages — each user turn sends
text + video (camera frames) + optional audio; model replies with audio + text.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXERCISES_JSON = Path(os.environ.get("PHYSIHOW_EXERCISES_JSON", str(_REPO_ROOT / "data" / "exercises.json")))

# Max size per video frame (1 MB); max frames per message
VIDEO_FRAME_MAX_BYTES = 1024 * 1024
VIDEO_FRAMES_MAX = 30
# Small delay between sending frames so the API isn't overwhelmed
FRAME_SEND_DELAY_SEC = 0.05


def _is_connection_closed(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "connectionclosed" in type(exc).__name__.lower()
        or "keepalive" in msg
        or "1007" in msg
        or "1011" in msg
    )


def _get_genai():
    try:
        from google import genai
        from google.genai import types
        return genai, types
    except ImportError as e:
        raise RuntimeError("google-genai required for the coach. Install with: pip install google-genai") from e


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


def _build_system_instruction(exercise: dict | None) -> str:
    if not exercise:
        return """You are a physiotherapy exercise coach. The user has not selected an exercise yet.
Suggest they pick an exercise from the app to get started."""

    name = exercise.get("name") or exercise.get("exerciseName", "")
    url = exercise.get("url") or exercise.get("sourceExerciseUrl", "")
    full_text = (exercise.get("fullText") or exercise.get("description") or "").strip() or (
        (exercise.get("introduction", "") or "")
        + "\n\n"
        + (exercise.get("technique", "") or "")
        + "\n\n"
        + (exercise.get("targetMuscles", "") or "")
    )
    return f"""You are a physiotherapy exercise coach guiding the user through: {name}.

Here is the full exercise information (from University of Melbourne CHESM knee/hip OA video library):
---
{full_text}
---
Source: {url}

Your job:
- Guide the user step by step through performing this exercise, using the instructions above as your primary reference.
- You receive periodic camera frames from the user alongside their audio. Only comment on what you can clearly see in those frames. If the image is unclear, dark, or does not show the relevant body part, say so — never invent form observations.
- Use phrases like "I can see..." only when you have a clear visual basis for the observation. When uncertain, ask the user to describe what they are doing or suggest they reposition the camera.
- Count reps if applicable.
- Answer questions about the exercise.
- Be encouraging and specific, but honest about the limits of what you can observe.
- When you instruct the user to hold a position, rest, or time any part of the exercise, first finish explaining what to do, then call start_timer. The session will pause until the timer finishes — after that you will be notified to continue coaching.
- When the user asks for alternative exercises or raises a concern about the current one, call suggest_exercise with their concern. You will receive a list of alternatives from the exercise library to read out."""


async def run_coach_session(websocket: "WebSocket"):
    """
    Run one coach session. First message: JSON { "exercise_slug": "Squat_Exercise" }.
    Then each user turn: JSON { "message": "text", "video_frames": ["base64",...], "audio_base64": "..." }.
    Video (camera stream) and text are required; audio_base64 optional. Model replies with audio + text.
    """
    genai, types = _get_genai()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        await websocket.close(code=1011, reason="GEMINI_API_KEY or GOOGLE_API_KEY not set")
        return

    exercise_slug: str | None = None
    exercise: dict | None = None

    # First message must be JSON with exercise_slug
    try:
        first = await asyncio.wait_for(websocket.receive(), timeout=30.0)
    except asyncio.TimeoutError:
        await websocket.send_json({"error": "Send exercise_slug first (JSON: { exercise_slug: \"Squat_Exercise\" })"})
        await websocket.close(code=1011, reason="Timeout waiting for exercise_slug")
        return
    if first.get("type") != "websocket.receive":
        await websocket.close(code=1011, reason="Invalid first message")
        return
    data = first.get("bytes") or first.get("text")
    if isinstance(data, bytes):
        await websocket.send_json({"error": "First message must be JSON with exercise_slug"})
        await websocket.close(code=1011, reason="Send exercise_slug first")
        return
    try:
        obj = json.loads(data) if isinstance(data, str) else data
        exercise_slug = (obj.get("exercise_slug") or obj.get("exerciseSlug") or "").strip()
    except json.JSONDecodeError:
        pass
    if exercise_slug:
        exercise = _load_exercise_by_slug(exercise_slug)
        if not exercise:
            await websocket.send_json({"error": f"Exercise not found: {exercise_slug!r}"})
            await websocket.close(code=1011, reason="Exercise not found")
            return
    system_text = _build_system_instruction(exercise)
    model_id = os.environ.get("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(role="system", parts=[types.Part(text=system_text)]),
        input_audio_transcription={},
        output_audio_transcription={},
        tools=[types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="start_timer",
                description=(
                    "Start a countdown timer for the user and pause the session until it finishes. "
                    "Finish speaking before calling this — the session resumes automatically when the timer ends."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "seconds": types.Schema(type="INTEGER", description="Duration in seconds"),
                        "label":   types.Schema(type="STRING",  description="Short label shown on screen, e.g. 'Hold stretch'"),
                    },
                    required=["seconds"],
                ),
            ),
            types.FunctionDeclaration(
                name="suggest_exercise",
                description=(
                    "Fetch a list of alternative exercises from the CHESM library that suit the user's concern. "
                    "Call this when the user asks for alternatives or raises a concern about the current exercise."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "concern": types.Schema(type="STRING", description="The user's concern or reason for wanting an alternative"),
                    },
                    required=["concern"],
                ),
            ),
        ])],
    )
    connection_dead = False

    async def _notify(reason: str):
        try:
            await websocket.send_json({"error": reason})
        except Exception:
            pass

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        logger.exception("Failed to create Gen AI client")
        await websocket.send_json({"error": str(e)})
        await websocket.close(code=1011, reason="Backend configuration error")
        return

    try:
        async with client.aio.live.connect(model=model_id, config=config) as session:

            async def receive_from_gemini():
                nonlocal connection_dead
                try:
                    # session.receive() ends after each turn_complete; loop to support multi-turn.
                    while True:
                        async for message in session.receive():
                            # Tool calls arrive on message.tool_call, separate from server_content
                            if message.tool_call:
                                for fc in message.tool_call.function_calls:
                                    if fc.name == "start_timer":
                                        seconds = int(fc.args.get("seconds", 30))
                                        label = str(fc.args.get("label", "Timer"))
                                        # Tell frontend to start the countdown
                                        try:
                                            await websocket.send_json({
                                                "tool_call": "start_timer",
                                                "seconds": seconds,
                                                "label": label,
                                                "call_id": fc.id,
                                            })
                                        except Exception:
                                            pass
                                        # Block the session for the timer duration (1s ticks so we can bail early)
                                        for _ in range(seconds):
                                            if connection_dead:
                                                break
                                            await asyncio.sleep(1)
                                        # Notify frontend timer is done
                                        try:
                                            await websocket.send_json({"timer_complete": True, "label": label})
                                        except Exception:
                                            pass
                                        # Unblock Gemini — it will now resume speaking
                                        try:
                                            await session.send_tool_response(function_responses=[
                                                types.FunctionResponse(
                                                    id=fc.id,
                                                    name="start_timer",
                                                    response={"result": f"Timer '{label}' finished after {seconds} seconds. Continue coaching the user."},
                                                )
                                            ])
                                        except Exception as e:
                                            logger.debug("send_tool_response start_timer failed: %s", e)

                                    elif fc.name == "suggest_exercise":
                                        concern = str(fc.args.get("concern", "wants an alternative"))
                                        # Notify frontend we're consulting the Railtracks agent
                                        try:
                                            await websocket.send_json({
                                                "tool_calling": "suggest_exercise",
                                                "label": "Consulting exercise library…",
                                            })
                                        except Exception:
                                            pass
                                        # Call the Railtracks suggest_agent
                                        suggestions_text = ""
                                        try:
                                            from api.agents import suggest_agent
                                            import railtracks as rt
                                            prompt = (
                                                f"Current exercise slug: {exercise_slug or 'unknown'}\n"
                                                f"User concern: {concern}"
                                            )
                                            result = await rt.call(suggest_agent, prompt)
                                            suggestions_text = result.text
                                        except Exception as e:
                                            logger.warning("suggest_exercise Railtracks call failed: %s", e)
                                            suggestions_text = "Could not retrieve suggestions at this time."
                                        # Notify frontend agent call is done
                                        try:
                                            await websocket.send_json({"tool_done": "suggest_exercise"})
                                        except Exception:
                                            pass
                                        # Return suggestions to Gemini — it will read them out
                                        try:
                                            await session.send_tool_response(function_responses=[
                                                types.FunctionResponse(
                                                    id=fc.id,
                                                    name="suggest_exercise",
                                                    response={"suggestions": suggestions_text},
                                                )
                                            ])
                                        except Exception as e:
                                            logger.debug("send_tool_response suggest_exercise failed: %s", e)
                            sc = message.server_content
                            if not sc:
                                continue
                            if sc.model_turn:
                                for part in sc.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        await websocket.send_bytes(part.inline_data.data)
                            if getattr(sc, "input_transcription", None) and sc.input_transcription.text:
                                try:
                                    await websocket.send_json({
                                        "input_transcription": {
                                            "text": sc.input_transcription.text,
                                            "finished": getattr(sc.input_transcription, "finished", True),
                                        },
                                    })
                                except Exception:
                                    pass
                            if getattr(sc, "output_transcription", None) and sc.output_transcription.text:
                                try:
                                    await websocket.send_json({
                                        "output_transcription": {
                                            "text": sc.output_transcription.text,
                                            "finished": getattr(sc.output_transcription, "finished", True),
                                        },
                                    })
                                except Exception:
                                    pass
                            # Forward turn_complete so the frontend can reliably finalize coach bubbles
                            if sc.turn_complete:
                                try:
                                    await websocket.send_json({"turn_complete": True})
                                except Exception:
                                    pass
                            # Forward interrupted so the frontend can stop audio playback
                            if sc.interrupted:
                                try:
                                    await websocket.send_json({"interrupted": True})
                                except Exception:
                                    pass
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.exception("Gemini receive loop error: %s", e)
                    connection_dead = True

            recv_task = asyncio.create_task(receive_from_gemini())

            try:
                while True:
                    if connection_dead:
                        break
                    # If the Gemini receive task exited unexpectedly the session is dead
                    if recv_task.done() and not recv_task.cancelled():
                        exc = recv_task.exception()
                        if exc:
                            logger.warning("Gemini receive task exited with error: %s", exc)
                        else:
                            logger.warning("Gemini receive task ended unexpectedly (session closed by server)")
                        connection_dead = True
                        await _notify("Connection to Gemini lost. Please refresh to start a new session.")
                        break
                    try:
                        msg = await asyncio.wait_for(websocket.receive(), timeout=300.0)
                    except asyncio.TimeoutError:
                        break
                    if msg["type"] == "websocket.disconnect":
                        break
                    if msg["type"] != "websocket.receive":
                        continue
                    data = msg.get("bytes") or msg.get("text")
                    if data is None:
                        continue
                    try:
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        obj = json.loads(data) if isinstance(data, str) else data
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue

                    # Streaming video frame (sent every ~1.5s alongside audio for continuous context)
                    video_chunk_b64 = obj.get("video_chunk_b64")
                    if video_chunk_b64 and isinstance(video_chunk_b64, str) and not connection_dead:
                        try:
                            jpeg_bytes = base64.standard_b64decode(video_chunk_b64)
                            if 0 < len(jpeg_bytes) <= VIDEO_FRAME_MAX_BYTES:
                                await session.send_realtime_input(
                                    video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
                                )
                        except Exception as e:
                            logger.debug("send_realtime_input video chunk failed: %s", e)
                        continue

                    # Streaming audio chunk (user speaking naturally): forward directly to Gemini
                    # The frontend pauses sending while coachGenerating=true, so these only arrive
                    # when the user is genuinely speaking (not while the model is responding).
                    audio_chunk_b64 = obj.get("audio_chunk_base64")
                    if audio_chunk_b64 and isinstance(audio_chunk_b64, str) and not connection_dead:
                        try:
                            audio_bytes = base64.standard_b64decode(audio_chunk_b64)
                            if 0 < len(audio_bytes) <= 64 * 1024:  # max 64 KB per chunk
                                await session.send_realtime_input(
                                    audio=types.Blob(
                                        data=audio_bytes, mime_type="audio/pcm;rate=16000"
                                    )
                                )
                        except Exception as e:
                            logger.debug("send_realtime_input audio chunk failed: %s", e)
                        continue

                    # Full turn: message + video_frames + optional audio_base64 (text and/or voice)
                    user_text = (obj.get("message") or "").strip()
                    video_frames = obj.get("video_frames") or []
                    if not isinstance(video_frames, list):
                        video_frames = []
                    video_frames = video_frames[:VIDEO_FRAMES_MAX]
                    audio_b64 = obj.get("audio_base64")
                    if not user_text and not video_frames and not (audio_b64 and isinstance(audio_b64, str)):
                        continue
                    if not user_text and audio_b64:
                        user_text = "[Voice message]"
                    if connection_dead:
                        break
                    try:
                        # 1) Video: camera stream appended to the message
                        for b64 in video_frames:
                            if not isinstance(b64, str):
                                continue
                            try:
                                jpeg_bytes = base64.standard_b64decode(b64)
                            except Exception:
                                continue
                            if 0 < len(jpeg_bytes) <= VIDEO_FRAME_MAX_BYTES:
                                await session.send_realtime_input(
                                    video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
                                )
                                await asyncio.sleep(FRAME_SEND_DELAY_SEC)
                        # 2) Text
                        if user_text:
                            await session.send_realtime_input(text=user_text)
                        # 3) Optional audio (user's speech)
                        if audio_b64 and isinstance(audio_b64, str):
                            try:
                                audio_bytes = base64.standard_b64decode(audio_b64)
                                if 0 < len(audio_bytes) <= 1024 * 1024:  # max 1 MB
                                    await session.send_realtime_input(
                                        audio=types.Blob(
                                            data=audio_bytes, mime_type="audio/pcm;rate=16000"
                                        )
                                    )
                            except Exception as e:
                                logger.warning("send_realtime_input audio from message failed: %s", e)
                    except Exception as e:
                        if _is_connection_closed(e):
                            connection_dead = True
                            await _notify("Connection lost. Reconnect by starting the stream again.")
                            break
                        logger.warning("send_realtime_input multimodal failed: %s", e)
            finally:
                recv_task.cancel()
                try:
                    await recv_task
                except asyncio.CancelledError:
                    pass
        if connection_dead:
            try:
                await websocket.close(code=1011, reason="Connection lost. Reconnect by starting the stream again.")
            except Exception:
                pass
    except Exception as e:
        logger.exception("Coach session error: %s", e)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
        try:
            await websocket.close(code=1011, reason=str(e)[:123])
        except Exception:
            pass
    except asyncio.CancelledError:
        pass
