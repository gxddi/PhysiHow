/**
 * Queues and plays 24-bit PCM audio chunks from the coach in real-time.
 * Chunks are scheduled back-to-back so playback is gapless.
 */

const COACH_SAMPLE_RATE = 24000;

let audioCtx: AudioContext | null = null;
let nextPlayTime = 0;
const scheduledSources: AudioBufferSourceNode[] = [];

function getCtx(): AudioContext {
  if (!audioCtx || audioCtx.state === "closed") {
    audioCtx = new AudioContext({ sampleRate: COACH_SAMPLE_RATE });
    nextPlayTime = 0;
  }
  return audioCtx;
}

/** Schedule a raw 16-bit PCM chunk for immediate (gapless) playback. */
export function playCoachChunk(data: ArrayBuffer): void {
  const ctx = getCtx();
  const int16 = new Int16Array(data);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 0x8000;
  }

  const audioBuffer = ctx.createBuffer(1, float32.length, COACH_SAMPLE_RATE);
  audioBuffer.copyToChannel(float32, 0);

  const source = ctx.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(ctx.destination);

  // Schedule immediately after the previous chunk so there are no gaps
  const now = ctx.currentTime;
  if (nextPlayTime < now) nextPlayTime = now;
  source.start(nextPlayTime);
  nextPlayTime += audioBuffer.duration;

  scheduledSources.push(source);
  source.onended = () => {
    const idx = scheduledSources.indexOf(source);
    if (idx !== -1) scheduledSources.splice(idx, 1);
  };
}

/**
 * Schedule a callback to run after all currently queued audio finishes playing.
 * If nothing is playing the callback fires immediately (next microtask).
 */
export function scheduleAfterAudio(callback: () => void): void {
  const ctx = getCtx();
  const remainingMs = Math.max(0, (nextPlayTime - ctx.currentTime) * 1000);
  if (remainingMs <= 0) {
    callback();
  } else {
    setTimeout(callback, remainingMs);
  }
}

/** Stop all queued coach audio immediately and reset the playback clock. */
export function stopCoachAudio(): void {
  for (const src of scheduledSources) {
    try {
      src.stop();
    } catch {
      // already stopped
    }
  }
  scheduledSources.length = 0;
  if (audioCtx) {
    audioCtx.close().catch(() => {});
    audioCtx = null;
  }
  nextPlayTime = 0;
}
