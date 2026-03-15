# PhysiHow — Feature Reference

## Target audience
Elderly patients managing **knee and/or hip osteoarthritis**, performing home physiotherapy exercises sourced from the University of Melbourne CHESM video library.

---

## Exercise catalog

| Feature | Detail |
|---|---|
| Source | University of Melbourne CHESM knee & hip OA video library |
| Storage | `data/exercises.json` — static, no external API dependency |
| Exercises | 10 curated exercises (e.g. seated knee extension, sit-to-stand, step ups, partial wall squats, hip abduction) |
| Attributes | `name`, `slug`, `description`, `introduction`, `technique`, `targetMuscles`, `sourceExerciseUrl` |
| API endpoint | `GET /api/exercises` — returns list; `GET /api/exercises/{slug}` — returns single exercise |

---

## Exercise picker (home screen)

- Grid of exercise cards loaded from the backend catalog
- Each card shows exercise name and a direct link to its CHESM video page
- Live search/filter across all exercise names
- Hover lift-and-glow effect on cards
- **Start** button navigates to the session screen with the selected exercise slug in the URL query string
- Fully responsive; collapses to single-column on mobile

---

## Coach session screen

### Layout
- **Left panel** — agentic tools sidebar (hidden on screens < 900 px)
- **Centre** — full-screen live camera feed (mirrored, `object-fit: cover`)
- **Right panel** — AI coach chat panel

### Camera
- Accesses device camera via `getUserMedia`
- Streams video to a `<video>` element; frames are captured to an off-screen `<canvas>` at ~1 fps and base64-encoded as JPEG
- Maintains a circular frame buffer; the most recent frame is always available for snapshot or streaming

### Microphone
- Continuous capture via `AudioContext` + `ScriptProcessorNode` at 16 kHz mono PCM
- Audio chunks are buffered client-side every 200 ms and streamed to the backend as base64-encoded payloads
- Mic streaming is automatically **muted** while the coach is speaking (prevents Gemini VAD from treating coach audio as user input) and while a timer is running

---

## AI coach (Gemini Live)

### Connection
- Persistent WebSocket to `ws://localhost:8000/api/coach`
- First message: `{ "exercise_slug": "..." }` — backend resolves exercise, builds system prompt, opens Gemini Live session
- Model: `gemini-2.5-flash-native-audio-preview` (configurable via `GEMINI_LIVE_MODEL` env var)

### Multimodal input
| Stream | Rate | Transport |
|---|---|---|
| Microphone audio | 16 kHz PCM chunks every 200 ms | `session.send_realtime_input(audio=...)` |
| Camera video | 1 JPEG frame every 1.5 s | `session.send_realtime_input(video=...)` |

### Output
- **Audio**: 24 kHz 16-bit PCM streamed back as binary WebSocket frames, scheduled gaplessly via the Web Audio API (`AudioContext` + `BufferSource` nodes on a `nextPlayTime` cursor)
- **Transcription**: output transcription chunks forwarded as JSON, appended to coach chat bubbles in real time; finalized on `output_transcription.finished`
- **Input transcription**: user speech transcribed by Gemini and displayed as user chat bubbles with a thumbnail of the current camera frame

### Conversation model
- Multi-turn: `session.receive()` is re-entered in a `while True` loop after each `turn_complete`, supporting unlimited back-and-forth
- `interrupted` signal stops audio playback immediately and resets state
- Fallback timeout (4 s of silence after audio arrives) finalizes a turn if `turn_complete` never fires

### System prompt grounding
- Full CHESM exercise description injected at session start
- Coach instructed to only comment on what is clearly visible in camera frames, and to acknowledge uncertainty rather than invent form observations
- Coach instructed to finish speaking before calling any tool

---

## Agentic tools

### Timer (native Gemini Live function calling)
- `start_timer(seconds, label)` declared as a `FunctionDeclaration` in `LiveConnectConfig.tools`
- When called by the model, backend immediately sends `{ "tool_call": "start_timer", ... }` to the frontend
- Frontend defers the visible countdown via `scheduleAfterAudio()` — which computes `nextPlayTime − audioContext.currentTime` — so the timer never starts while the coach is still audibly speaking
- Backend blocks the Gemini Live session with `asyncio.sleep(1)` × N ticks; `send_tool_response` is withheld until the full duration elapses, preventing the model from generating a new turn during the hold
- On completion: `{ "timer_complete": true }` sent to frontend, `timerRunning` flag cleared (re-enables mic stream), tool response unblocks Gemini
- Manual override: user can also start a timer from the toolbar and send a message to the coach

### Exercise suggestion (Railtracks agent)
- `suggest_exercise(concern)` declared as a `FunctionDeclaration` alongside the timer
- When triggered, backend sends `{ "tool_calling": "suggest_exercise" }` status frame → frontend shows "Consulting exercise library…" and sets `coachGenerating = true`
- Backend runs `await rt.call(suggest_agent, prompt)` — a Railtracks `agent_node` backed by a separate Gemini 2.5 Flash instance
- Agent has a `@rt.function_node` (`get_exercises`) that reads `exercises.json` and returns name, slug, and 300-char intro for every exercise
- Railtracks handles the internal function-call loop; `result.text` is returned to the Live session as the tool response — the coach reads suggestions aloud
- Also accessible directly from the toolbar sidebar (POST to `/api/suggest-exercise`) without going through the coach

### Session notes compiler (Railtracks agent)
- Toolbar button scrapes all chat bubble text from the DOM and joins it as the session transcript
- User can add free-form notes in the sidebar textarea
- Frontend POSTs `{ exercise_name, transcript, user_notes }` to `/api/compile-session`
- Backend calls `await rt.call(notes_agent, prompt)` — a Railtracks `agent_node` with no tools; compiles the transcript into a structured Markdown document with headings: Date · Exercise · Session Summary · Form Observations · Reps/Sets · Coach Feedback · Recommended Next Steps
- Frontend triggers a browser download of the `.md` file

---

## UI / UX

- **Green + white design system** — lime-green (`#22c55e`) accent on pure white; dark session screen with white side panels
- Split-colour logo: **Physi** (near-black) + **How** (lime-green)
- Coach status indicator: animated pulse dot (Ready · Speaking · Consulting… · Error)
- Streaming coach text — transcription appended word-by-word as audio plays
- User speech bubbles include a thumbnail of the camera frame at time of speaking
- Audio playback indicator on each coach bubble (native `<audio>` element with WAV blob URL)
- Back button returns to exercise picker and tears down the WebSocket + mic + camera cleanly

---

## Backend (FastAPI)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/exercises` | GET | List all exercises |
| `/api/exercises/{slug}` | GET | Single exercise detail |
| `/api/coach` | WebSocket | Gemini Live proxy session |
| `/api/suggest-exercise` | POST | Railtracks suggest_agent |
| `/api/compile-session` | POST | Railtracks notes_agent |
| `/api/health` | GET | Liveness check |

- CORS open for local Vite dev server (`http://localhost:5173`)
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) loaded from `.env`
- Default port: **8000**

---

## Environment & tooling

| Item | Detail |
|---|---|
| Backend runtime | Python 3.12, FastAPI, Uvicorn, `google-genai`, `railtracks` |
| Frontend runtime | TypeScript, Vite, Web Audio API, WebSocket |
| Exercise data | Static JSON — no scraper needed at runtime |
| Dev start | `uvicorn api.main:app --reload --port 8000` + `npm run dev` |
| Windows helper | `scripts/run_api.bat` / `scripts/run_api_no_reload.bat` |
