/**
 * Captures microphone audio as 16-bit PCM at 16 kHz and delivers chunks via a callback.
 * Uses ScriptProcessorNode for broad browser compatibility.
 */

const MIC_SAMPLE_RATE = 16000;
const SCRIPT_PROCESSOR_BUFFER = 4096;

export interface MicStreamOptions {
  onChunk: (pcm: ArrayBuffer) => void;
}

export async function startMicStream(
  options: MicStreamOptions
): Promise<{ stop: () => void }> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { sampleRate: MIC_SAMPLE_RATE, channelCount: 1, echoCancellation: true },
    video: false,
  });

  const ctx = new AudioContext({ sampleRate: MIC_SAMPLE_RATE });
  const source = ctx.createMediaStreamSource(stream);

  // ScriptProcessorNode is deprecated but remains the most reliable cross-browser
  // option for raw PCM access without requiring an AudioWorklet file.
  const processor = ctx.createScriptProcessor(SCRIPT_PROCESSOR_BUFFER, 1, 1);

  processor.onaudioprocess = (e: AudioProcessingEvent) => {
    const float32 = e.inputBuffer.getChannelData(0);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const clamped = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    }
    options.onChunk(int16.buffer.slice(0));
  };

  source.connect(processor);
  // ScriptProcessorNode requires a destination connection to fire onaudioprocess
  processor.connect(ctx.destination);

  return {
    stop: () => {
      processor.disconnect();
      source.disconnect();
      ctx.close().catch(() => {});
      stream.getTracks().forEach((t) => t.stop());
    },
  };
}
