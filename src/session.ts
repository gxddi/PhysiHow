/**
 * Camera + coach session: multimodal messages (text + video from camera + optional audio).
 * Each user message bundles camera stream + text + optional mic; coach replies with audio + text.
 */
import { getExerciseBySlug, type ExerciseDetail } from "./api.js";
import { startMicStream } from "./coach/audio-in.js";
import { playCoachChunk, stopCoachAudio } from "./coach/audio-out.js";
import { setCoachOverlayStatus } from "./coach/view.js";

const VIDEO_BUFFER_FPS = 1;
const VIDEO_MAX_FRAMES = 10;
const VIDEO_MAX_WIDTH = 480;
const JPEG_QUALITY = 0.6;
const AUDIO_BUFFER_MS = 3000;
const PCM_SAMPLE_RATE = 16000;
const PCM_BYTES_PER_SAMPLE = 2;

function getCoachWsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/coach`;
}

/** Build a WAV blob from 16-bit PCM mono. */
function buildWavBlob(pcmChunks: ArrayBuffer[], sampleRate: number = 24000): Blob {
  const totalLen = pcmChunks.reduce((a, c) => a + c.byteLength, 0);
  const numSamples = totalLen / 2;
  const byteRate = sampleRate * 2;
  const dataSize = numSamples * 2;
  const headerLen = 44;
  const buffer = new ArrayBuffer(headerLen + dataSize);
  const view = new DataView(buffer);
  const writeStr = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);
  let offset = headerLen;
  for (const chunk of pcmChunks) {
    new Uint8Array(buffer).set(new Uint8Array(chunk), offset);
    offset += chunk.byteLength;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export function initSession(mountEl: HTMLElement, exerciseSlug: string, onBack: () => void): void {
  let stream: MediaStream | null = null;
  let videoEl: HTMLVideoElement | null = null;
  let canvasEl: HTMLCanvasElement | null = null;
  let ws: WebSocket | null = null;
  let micStop: (() => void) | null = null;
  let videoIntervalId: ReturnType<typeof setInterval> | null = null;
  const videoFrameBuffer: string[] = [];
  const audioChunkBuffer: ArrayBuffer[] = [];
  let audioBufferByteLength = 0;
  const maxAudioBytes = (AUDIO_BUFFER_MS / 1000) * PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE;
  let modelAudioChunks: ArrayBuffer[] = [];
  let currentModelText = "";
  /** Pending coach bubble we update with streaming text until turn is finished */
  let pendingCoachBubble: { wrap: HTMLDivElement; textEl: HTMLParagraphElement } | null = null;
  let responseDoneTimeoutId: ReturnType<typeof setTimeout> | null = null;
  /** Accumulate user speech transcription so we can show it in chat with video */
  let currentUserTranscriptionText = "";
  let lastUserBubbleTime = 0;
  /** Mute mic streaming while the coach is generating so we don't trigger Gemini VAD mid-response */
  let coachGenerating = false;
  /** Chunks to send as streaming audio to the coach (natural speech) */
  const streamAudioBuffer: ArrayBuffer[] = [];
  let streamAudioIntervalId: ReturnType<typeof setInterval> | null = null;
  const STREAM_AUDIO_MS = 200;
  let videoStreamIntervalId: ReturnType<typeof setInterval> | null = null;
  const STREAM_VIDEO_MS = 1500;

  function cleanup(): void {
    if (responseDoneTimeoutId) {
      clearTimeout(responseDoneTimeoutId);
      responseDoneTimeoutId = null;
    }
    if (streamAudioIntervalId) {
      clearInterval(streamAudioIntervalId);
      streamAudioIntervalId = null;
    }
    if (videoStreamIntervalId) {
      clearInterval(videoStreamIntervalId);
      videoStreamIntervalId = null;
    }
    if (videoIntervalId) {
      clearInterval(videoIntervalId);
      videoIntervalId = null;
    }
    if (micStop) {
      micStop();
      micStop = null;
    }
    stopCoachAudio();
    if (ws && ws.readyState === WebSocket.OPEN) ws.close();
    ws = null;
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    videoEl = null;
    canvasEl = null;
  }

  mountEl.innerHTML = `
    <div class="session-screen">
      <div class="session-camera-wrap">
        <video id="session-video" playsinline muted autoplay></video>
        <canvas id="session-canvas" style="display: none;"></canvas>
      </div>
      <aside class="coach-panel session-coach-panel">
        <div class="coach-panel-header">
          <span class="coach-panel-title">Coach</span>
          <span id="coach-overlay-status" class="coach-panel-status">—</span>
        </div>
        <p id="coach-active-name" class="coach-active-name">—</p>
        <a id="coach-source-link" class="coach-source-link" href="#" target="_blank" rel="noopener noreferrer">View in video library</a>
        <div id="coach-overlay-transcript" class="coach-panel-transcript">
          <p class="coach-transcript-placeholder">Loading…</p>
        </div>
        <div class="chat-input-row">
          <input type="text" id="session-chat-input" class="chat-input" placeholder="Speak naturally or type a message… (camera attached)" />
          <button type="button" id="session-send" class="btn btn-primary chat-send">Send</button>
        </div>
        <button type="button" id="session-back" class="btn btn-secondary session-back">Back</button>
      </aside>
    </div>
  `;

  const backBtn = mountEl.querySelector<HTMLButtonElement>("#session-back");
  backBtn?.addEventListener("click", () => {
    cleanup();
    onBack();
  });

  const nameEl = mountEl.querySelector<HTMLParagraphElement>("#coach-active-name");
  const linkEl = mountEl.querySelector<HTMLAnchorElement>("#coach-source-link");
  const transcriptEl = mountEl.querySelector<HTMLDivElement>("#coach-overlay-transcript");
  const inputEl = mountEl.querySelector<HTMLInputElement>("#session-chat-input");
  const sendBtn = mountEl.querySelector<HTMLButtonElement>("#session-send");
  videoEl = mountEl.querySelector<HTMLVideoElement>("#session-video");
  canvasEl = mountEl.querySelector<HTMLCanvasElement>("#session-canvas");

  function clearPlaceholder(): void {
    if (!transcriptEl) return;
    const p = transcriptEl.querySelector(".coach-transcript-placeholder");
    if (p) p.remove();
  }

  function setPlaceholder(text: string): void {
    if (!transcriptEl) return;
    let p = transcriptEl.querySelector(".coach-transcript-placeholder");
    if (!p) {
      p = document.createElement("p");
      p.className = "coach-transcript-placeholder";
      transcriptEl.prepend(p);
    }
    p.textContent = text;
  }

  function appendUserBubble(text: string, firstFrameDataUrl?: string, userAudioUrl?: string): void {
    if (!transcriptEl) return;
    clearPlaceholder();
    const wrap = document.createElement("div");
    wrap.className = "chat-turn chat-turn-user";
    const label = document.createElement("div");
    label.className = "chat-turn-label";
    label.textContent = "You";
    wrap.appendChild(label);
    if (firstFrameDataUrl) {
      const vid = document.createElement("div");
      vid.className = "chat-turn-video";
      const img = document.createElement("img");
      img.src = firstFrameDataUrl;
      img.alt = "Camera";
      img.loading = "lazy";
      vid.appendChild(img);
      wrap.appendChild(vid);
    }
    if (userAudioUrl) {
      const aud = document.createElement("audio");
      aud.controls = true;
      aud.src = userAudioUrl;
      aud.className = "chat-turn-audio";
      wrap.appendChild(aud);
    }
    if (text) {
      const p = document.createElement("p");
      p.className = "chat-turn-text";
      p.textContent = text;
      wrap.appendChild(p);
    }
    transcriptEl.appendChild(wrap);
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }

  function appendModelBubble(text: string, modelAudioUrl?: string): void {
    if (!transcriptEl) return;
    pendingCoachBubble = null;
    const wrap = document.createElement("div");
    wrap.className = "chat-turn chat-turn-model";
    const label = document.createElement("div");
    label.className = "chat-turn-label";
    label.textContent = "Coach";
    wrap.appendChild(label);
    if (modelAudioUrl) {
      const aud = document.createElement("audio");
      aud.controls = true;
      aud.src = modelAudioUrl;
      aud.className = "chat-turn-audio";
      wrap.appendChild(aud);
    }
    if (text) {
      const p = document.createElement("p");
      p.className = "chat-turn-text";
      p.textContent = text;
      wrap.appendChild(p);
    }
    transcriptEl.appendChild(wrap);
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }

  /** Create or update the streaming coach bubble; call appendModelBubble when finished. */
  function updateOrCreateCoachStreamingBubble(text: string): void {
    if (!transcriptEl) return;
    if (pendingCoachBubble) {
      pendingCoachBubble.textEl.textContent = text;
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
      return;
    }
    const wrap = document.createElement("div");
    wrap.className = "chat-turn chat-turn-model chat-turn-model-pending";
    const label = document.createElement("div");
    label.className = "chat-turn-label";
    label.textContent = "Coach";
    wrap.appendChild(label);
    const p = document.createElement("p");
    p.className = "chat-turn-text";
    p.textContent = text;
    wrap.appendChild(p);
    transcriptEl.appendChild(wrap);
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
    pendingCoachBubble = { wrap, textEl: p };
  }

  function finalizeCoachBubble(audioUrl?: string): void {
    if (!transcriptEl || !pendingCoachBubble) return;
    if (audioUrl) {
      const aud = document.createElement("audio");
      aud.controls = true;
      aud.src = audioUrl;
      aud.className = "chat-turn-audio";
      pendingCoachBubble.wrap.appendChild(aud);
    }
    pendingCoachBubble.wrap.classList.remove("chat-turn-model-pending");
    pendingCoachBubble = null;
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }

  getExerciseBySlug(exerciseSlug)
    .then((ex: ExerciseDetail) => {
      if (nameEl) nameEl.textContent = ex.name;
      if (linkEl) {
        linkEl.href = ex.url;
        linkEl.textContent = "View in video library";
      }
      setCoachOverlayStatus("Connecting…", "idle");
      return startCamera();
    })
    .then(() => connectCoach(exerciseSlug))
    .catch((err) => {
      setCoachOverlayStatus(err.message || "Failed to start", "error");
      setPlaceholder(`Error: ${err.message}`);
    });

  function startCamera(): Promise<void> {
    return navigator.mediaDevices
      .getUserMedia({ video: true, audio: true })
      .then((s) => {
        stream = s;
        if (!videoEl) return;
        videoEl.srcObject = s;
        return new Promise<void>((resolve) => {
          videoEl!.onloadedmetadata = () => {
            videoEl!.play().then(() => resolve()).catch(() => resolve());
          };
        });
      })
      .catch(() => Promise.resolve());
  }

  function connectCoach(slug: string): void {
    const url = getCoachWsUrl();
    ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      ws!.send(JSON.stringify({ exercise_slug: slug }));
      clearPlaceholder();
      setPlaceholder("Speak naturally or type a message and press Send. Camera is attached.");
      setCoachOverlayStatus("Ready", "ready");

      // Video buffer: capture frame every 1 sec, keep last VIDEO_MAX_FRAMES
      videoIntervalId = setInterval(() => {
        if (!videoEl || !canvasEl || videoEl.readyState < 2 || videoEl.videoWidth <= 0) return;
        const w = videoEl.videoWidth;
        const h = videoEl.videoHeight;
        const scale = w > VIDEO_MAX_WIDTH ? VIDEO_MAX_WIDTH / w : 1;
        canvasEl.width = Math.round(w * scale);
        canvasEl.height = Math.round(h * scale);
        const ctx = canvasEl.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(videoEl, 0, 0, canvasEl.width, canvasEl.height);
        canvasEl.toBlob(
          (blob) => {
            if (!blob) return;
            const reader = new FileReader();
            reader.onloadend = () => {
              const b64 = (reader.result as string).split(",")[1];
              if (b64) {
                videoFrameBuffer.push(b64);
                if (videoFrameBuffer.length > VIDEO_MAX_FRAMES) videoFrameBuffer.shift();
              }
            };
            reader.readAsDataURL(blob);
          },
          "image/jpeg",
          JPEG_QUALITY
        );
      }, 1000 / VIDEO_BUFFER_FPS);

      // Mic: buffer for last AUDIO_BUFFER_MS (for Send); also accumulate for streaming to coach
      startMicStream({
        onChunk: (pcm: ArrayBuffer) => {
          audioChunkBuffer.push(pcm);
          audioBufferByteLength += pcm.byteLength;
          while (audioBufferByteLength > maxAudioBytes && audioChunkBuffer.length > 1) {
            const first = audioChunkBuffer.shift()!;
            audioBufferByteLength -= first.byteLength;
          }
          streamAudioBuffer.push(pcm.slice(0));
        },
      }).then((r) => {
        micStop = r.stop;
      });

      // Stream mic to coach every STREAM_AUDIO_MS so user can speak naturally (like AI Studio)
      // Paused while coachGenerating to avoid triggering Gemini VAD and interrupting its response.
      streamAudioIntervalId = setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN || streamAudioBuffer.length === 0) return;
        if (coachGenerating) {
          // Discard so stale silence doesn't flood Gemini the moment the model finishes
          streamAudioBuffer.length = 0;
          return;
        }
        const chunks = streamAudioBuffer.splice(0, streamAudioBuffer.length);
        const total = chunks.reduce((a, c) => a + c.byteLength, 0);
        if (total === 0) return;
        const combined = new Uint8Array(total);
        let off = 0;
        for (const c of chunks) {
          combined.set(new Uint8Array(c), off);
          off += c.byteLength;
        }
        const b64 = btoa(String.fromCharCode(...combined));
        try {
          ws.send(JSON.stringify({ audio_chunk_base64: b64 }));
        } catch {
          // ignore
        }
      }, STREAM_AUDIO_MS);

      // Stream the latest video frame every STREAM_VIDEO_MS so Gemini has camera context
      // during voice turns (not just when the user explicitly presses Send).
      // Paused while coachGenerating to avoid flooding the model while it is responding.
      videoStreamIntervalId = setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (coachGenerating) return;
        if (videoFrameBuffer.length === 0) return;
        const frame = videoFrameBuffer[videoFrameBuffer.length - 1];
        try {
          ws.send(JSON.stringify({ video_chunk_b64: frame }));
        } catch {
          // ignore
        }
      }, STREAM_VIDEO_MS);

      sendBtn?.addEventListener("click", onSend);
      inputEl?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") onSend();
      });
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        try {
          const obj = JSON.parse(event.data);
          if (obj.error) {
            setCoachOverlayStatus(obj.error, "error");
            return;
          }
          // Show user's transcribed speech in chat (with video thumbnail) so coach reply has context
          if (obj.input_transcription?.text != null) {
            // Preserve natural spaces: just append the raw chunk, trim only for display
            currentUserTranscriptionText += obj.input_transcription.text;
            if (obj.input_transcription.finished === true) {
              const trimmed = currentUserTranscriptionText.trim();
              if (trimmed) {
                const now = Date.now();
                if (now - lastUserBubbleTime > 500) {
                  const frameUrl = videoFrameBuffer.length > 0
                    ? `data:image/jpeg;base64,${videoFrameBuffer[0]}`
                    : undefined;
                  appendUserBubble(trimmed, frameUrl, undefined);
                  lastUserBubbleTime = now;
                }
              }
              currentUserTranscriptionText = "";
            }
          }
          if (obj.output_transcription?.text != null) {
            coachGenerating = true;
            // Preserve natural spaces: just append the raw chunk, trim only for display
            currentModelText += obj.output_transcription.text;
            updateOrCreateCoachStreamingBubble(currentModelText.trim());
            if (obj.output_transcription.finished === true) {
              if (responseDoneTimeoutId) {
                clearTimeout(responseDoneTimeoutId);
                responseDoneTimeoutId = null;
              }
              const url = modelAudioChunks.length > 0
                ? URL.createObjectURL(buildWavBlob(modelAudioChunks, 24000))
                : undefined;
              if (pendingCoachBubble) {
                finalizeCoachBubble(url);
              } else {
                appendModelBubble(
                  currentModelText.trim() || "Listen to the coach above.",
                  url
                );
              }
              modelAudioChunks = [];
              currentModelText = "";
              coachGenerating = false;
              setCoachOverlayStatus("Ready", "ready");
            }
          }
          // turn_complete: reliable signal from Gemini that the model finished its turn
          if (obj.turn_complete) {
            if (responseDoneTimeoutId) {
              clearTimeout(responseDoneTimeoutId);
              responseDoneTimeoutId = null;
            }
            // Flush any pending user transcription (in case finished never arrived)
            if (currentUserTranscriptionText.trim()) {
              const frameUrl = videoFrameBuffer.length > 0
                ? `data:image/jpeg;base64,${videoFrameBuffer[0]}`
                : undefined;
              const now = Date.now();
              if (now - lastUserBubbleTime > 500) {
                appendUserBubble(currentUserTranscriptionText.trim(), frameUrl, undefined);
                lastUserBubbleTime = now;
              }
              currentUserTranscriptionText = "";
            }
            // Finalize coach bubble if output_transcription.finished didn't already do it
            const url = modelAudioChunks.length > 0
              ? URL.createObjectURL(buildWavBlob(modelAudioChunks, 24000))
              : undefined;
            if (pendingCoachBubble) {
              finalizeCoachBubble(url);
            } else if (currentModelText.trim() || url) {
              appendModelBubble(currentModelText.trim() || "Listen to the coach above.", url);
            }
            modelAudioChunks = [];
            currentModelText = "";
            coachGenerating = false;
            setCoachOverlayStatus("Ready", "ready");
          }
          // interrupted: model was cut off — stop audio and reset state
          if (obj.interrupted) {
            stopCoachAudio();
            if (responseDoneTimeoutId) {
              clearTimeout(responseDoneTimeoutId);
              responseDoneTimeoutId = null;
            }
            if (pendingCoachBubble) {
              const url = modelAudioChunks.length > 0
                ? URL.createObjectURL(buildWavBlob(modelAudioChunks, 24000))
                : undefined;
              finalizeCoachBubble(url);
            }
            modelAudioChunks = [];
            currentModelText = "";
            coachGenerating = false;
          }
        } catch {
          // ignore
        }
      } else {
        modelAudioChunks.push(event.data as ArrayBuffer);
        playCoachChunk(event.data as ArrayBuffer);
        coachGenerating = true;
        setCoachOverlayStatus("Speaking", "speaking");
        if (!pendingCoachBubble && currentModelText === "" && modelAudioChunks.length === 1) {
          updateOrCreateCoachStreamingBubble("Coach is speaking…");
        }
        scheduleResponseDoneFallback();
      }
    };

    function scheduleResponseDoneFallback(): void {
      if (responseDoneTimeoutId) clearTimeout(responseDoneTimeoutId);
      responseDoneTimeoutId = setTimeout(() => {
        responseDoneTimeoutId = null;
        if (!pendingCoachBubble && modelAudioChunks.length === 0) return;
        const url = modelAudioChunks.length > 0
          ? URL.createObjectURL(buildWavBlob(modelAudioChunks, 24000))
          : undefined;
        if (pendingCoachBubble) {
          finalizeCoachBubble(url);
        } else {
          appendModelBubble(currentModelText || "Listen to the coach above.", url);
        }
        modelAudioChunks = [];
        currentModelText = "";
        coachGenerating = false;
        setCoachOverlayStatus("Ready", "ready");
      }, 4000);
    }

    ws.onclose = () => setCoachOverlayStatus("Disconnected", "idle");
    ws.onerror = () => setCoachOverlayStatus("Connection error", "error");
  }

  async function onSend(): Promise<void> {
    const input = inputEl;
    const send = sendBtn;
    if (!input || !send || !ws || ws.readyState !== WebSocket.OPEN) return;
    if (responseDoneTimeoutId) {
      clearTimeout(responseDoneTimeoutId);
      responseDoneTimeoutId = null;
    }
    const text = input.value.trim() || "(no text)";
    input.value = "";
    send.disabled = true;
    setCoachOverlayStatus("Sending…", "idle");

    try {
      const frames = [...videoFrameBuffer];
      let audioBase64 = "";
      if (audioChunkBuffer.length > 0) {
        const total = audioChunkBuffer.reduce((a, c) => a + c.byteLength, 0);
        const combined = new Uint8Array(total);
        let off = 0;
        for (const c of audioChunkBuffer) {
          combined.set(new Uint8Array(c), off);
          off += c.byteLength;
        }
        audioBase64 = btoa(String.fromCharCode(...combined));
      }

      const firstFrameDataUrl = frames.length > 0 ? `data:image/jpeg;base64,${frames[0]}` : undefined;
      let userAudioUrl: string | undefined;
      if (audioBase64) {
        try {
          const binary = Uint8Array.from(atob(audioBase64), (c) => c.charCodeAt(0));
          const wav = buildWavBlob([binary.buffer], PCM_SAMPLE_RATE);
          userAudioUrl = URL.createObjectURL(wav);
        } catch {
          // ignore
        }
      }
      appendUserBubble(text, firstFrameDataUrl, userAudioUrl);
      lastUserBubbleTime = Date.now();
      if (userAudioUrl) URL.revokeObjectURL(userAudioUrl);

      const socket = ws;
      socket.send(
        JSON.stringify({
          message: text,
          video_frames: frames,
          audio_base64: audioBase64 || undefined,
        })
      );
    } catch (err) {
      setCoachOverlayStatus("Error sending", "error");
    } finally {
      send.disabled = false;
      input?.focus();
      setCoachOverlayStatus("Ready", "ready");
      setTimeout(() => setCoachOverlayStatus("Ready", "ready"), 0);
      setTimeout(() => {
        const el = document.getElementById("coach-overlay-status");
        if (el?.textContent === "Sending…") setCoachOverlayStatus("Ready", "ready");
      }, 2500);
    }
  }
}
