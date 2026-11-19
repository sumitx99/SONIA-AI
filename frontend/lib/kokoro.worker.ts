// Runs the Kokoro voice model off the main thread, so the page stays smooth while it speaks.
// The model downloads once from Hugging Face and the browser keeps it in its cache.

import { KokoroTTS } from "kokoro-js";

const MODEL_ID = "onnx-community/Kokoro-82M-v1.0-ONNX";

type Request =
  | { type: "load"; dtype: "fp32" | "q8"; device: "webgpu" | "wasm" }
  | { type: "speak"; id: number; text: string; voice: string };

let tts: KokoroTTS | null = null;
const files = new Map<string, { loaded: number; total: number }>();

self.onmessage = async (event: MessageEvent<Request>) => {
  const request = event.data;
  if (request.type === "load") {
    try {
      tts = await KokoroTTS.from_pretrained(MODEL_ID, {
        dtype: request.dtype,
        device: request.device,
        progress_callback: (progress: { status: string; file?: string; loaded?: number; total?: number }) => {
          if (progress.status !== "progress" || !progress.file || !progress.total) return;
          files.set(progress.file, { loaded: progress.loaded ?? 0, total: progress.total });
          let loaded = 0, total = 0;
          for (const file of files.values()) { loaded += file.loaded; total += file.total; }
          self.postMessage({ type: "progress", loaded, total });
        },
      });
      // The first generation compiles the model's GPU kernels; do it now, not on the first reply.
      await tts.generate("Hi.", { voice: "af_heart" });
      self.postMessage({ type: "ready" });
    } catch (error) {
      self.postMessage({ type: "load-error", message: error instanceof Error ? error.message : String(error) });
    }
    return;
  }
  if (request.type === "speak") {
    try {
      if (!tts) throw new Error("The voice model isn't loaded.");
      const started = performance.now();
      const audio = await tts.generate(request.text, { voice: request.voice as never });
      self.postMessage({
        type: "audio", id: request.id, blob: audio.toBlob(),
        seconds: audio.audio.length / audio.sampling_rate,
        tookSeconds: (performance.now() - started) / 1000,
      });
    } catch (error) {
      self.postMessage({ type: "speak-error", id: request.id, message: error instanceof Error ? error.message : String(error) });
    }
  }
};
