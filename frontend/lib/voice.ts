// Voice mode building blocks, all running in the browser: listening (the browser's speech
// recognition, or the microphone with silence detection as a fallback), turning a streamed
// Markdown answer into speakable chunks, and speaking them with the HD voice (Kokoro) or the
// device's own voice.

import type { VoiceChoice } from "@/lib/api";

const wait = (ms: number, signal: AbortSignal) => new Promise<void>(resolve => {
  const timer = setTimeout(resolve, ms);
  signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
});

export function voiceSupported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
}

function recorderType(): string | undefined {
  const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  return types.find(type => MediaRecorder.isTypeSupported(type));
}

/** The microphone for one voice session: level metering, recording a turn, and barge-in. */
export class Microphone {
  private readonly context: AudioContext;
  private readonly analyser: AnalyserNode;
  private readonly samples: Float32Array<ArrayBuffer>;
  // A slowly adapting estimate of background noise, so a fan or a busy room isn't "speech".
  private noiseFloor = 0.01;

  private constructor(private readonly stream: MediaStream) {
    this.context = new AudioContext();
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 1024;
    this.samples = new Float32Array(this.analyser.fftSize);
    this.context.createMediaStreamSource(stream).connect(this.analyser);
  }

  static async open(): Promise<Microphone> {
    const stream = await navigator.mediaDevices.getUserMedia({
      // Echo cancellation keeps Sonia's own voice from being heard as the user speaking.
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    return new Microphone(stream);
  }

  /** Current input loudness (RMS, roughly 0–0.5 for speech). */
  level(): number {
    this.analyser.getFloatTimeDomainData(this.samples);
    let sum = 0;
    for (const sample of this.samples) sum += sample * sample;
    return Math.sqrt(sum / this.samples.length);
  }

  private threshold(factor: number, minimum: number) { return Math.max(minimum, this.noiseFloor * factor); }

  private track(level: number, threshold: number) {
    if (level < threshold) this.noiseFloor = this.noiseFloor * 0.95 + level * 0.05;
  }

  /**
   * Records one spoken turn: starts once the user speaks, ends after a pause.
   * Resolves null if nobody spoke within `noSpeechMs`, or when the session ends.
   */
  async record(signal: AbortSignal, onLevel: (level: number) => void,
    { silenceMs = 900, noSpeechMs = 20_000, maxMs = 90_000 } = {}): Promise<Blob | null> {
    if (this.context.state === "suspended") await this.context.resume();
    const type = recorderType();
    const recorder = new MediaRecorder(this.stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    const stopped = new Promise<void>(resolve => { recorder.onstop = () => resolve(); });
    recorder.start(250);
    const started = performance.now();
    let speechAt = 0, loudFor = 0, quietSince = 0;
    while (!signal.aborted) {
      await wait(50, signal);
      const level = this.level();
      const threshold = this.threshold(2.5, 0.015);
      onLevel(level);
      const now = performance.now();
      if (level > threshold) {
        loudFor += 50;
        quietSince = 0;
        if (!speechAt && loudFor >= 150) speechAt = now;
      } else {
        loudFor = 0;
        this.track(level, threshold);
        if (speechAt && !quietSince) quietSince = now;
      }
      if (speechAt && quietSince && now - quietSince >= silenceMs) break;
      if (!speechAt && now - started >= noSpeechMs) break;
      if (now - started >= maxMs) break;
    }
    recorder.stop();
    await stopped;
    onLevel(0);
    if (signal.aborted || !speechAt) return null;
    return new Blob(chunks, { type: recorder.mimeType || type || "audio/webm" });
  }

  /** Resolves true once the user clearly starts speaking (to interrupt Sonia), false when aborted. */
  async waitForSpeech(signal: AbortSignal, sustainMs = 400): Promise<boolean> {
    let loudFor = 0;
    while (!signal.aborted) {
      await wait(50, signal);
      // A higher bar than normal listening: what leaks past echo cancellation shouldn't interrupt.
      if (this.level() > this.threshold(5, 0.05)) {
        loudFor += 50;
        if (loudFor >= sustainMs) return true;
      } else loudFor = 0;
    }
    return false;
  }

  close() {
    this.stream.getTracks().forEach(track => track.stop());
    void this.context.close().catch(() => {});
  }
}

const SENTENCE_END = /[.!?।]+["'”’)\]]?(?=\s|$)/g;
const MAX_CHUNK = 1200;

/** Plain speakable text for one Markdown line ("" for lines that shouldn't be read aloud). */
export function speakableLine(line: string): string {
  const text = line.trim();
  if (!text || text.startsWith("|") || /^[-*_]{3,}$/.test(text)) return "";
  return text
    .replace(/^#{1,6}\s+/, "")
    .replace(/^>\s?/, "")
    .replace(/^(?:[-*+]|\d+[.)])\s+/, "")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\((?:[^)]*)\)/g, "$1")
    .replace(/\[\^?\d+(?:\s*,\s*\d+)*\]/g, "")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/<[^>]+>/g, "")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/[*`~]/g, "")
    .replace(/\s+([.,!?;:])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/**
 * Turns a streamed Markdown answer into chunks to speak, in order, as soon as sentences finish.
 * Code blocks, tables and the hidden citations block are skipped; the chat shows them.
 * `push` takes the whole answer so far; each call returns only the new chunks.
 */
export class SpeechChunker {
  private lineIndex = 0;
  private partialTaken = 0;
  private inFence = false;
  private pending = "";
  private emitted = 0;
  private skippedCode = false;

  push(raw: string): string[] {
    const lines = raw.split("\n");
    for (; this.lineIndex < lines.length - 1; this.lineIndex++) {
      const line = lines[this.lineIndex];
      if (line.trim().startsWith("```")) {
        this.inFence = !this.inFence;
        if (this.inFence && !/^```\s*citations/i.test(line.trim())) this.skippedCode = true;
        this.partialTaken = 0;
        continue;
      }
      if (!this.inFence) this.append(speakableLine(line).slice(this.partialTaken), true);
      this.partialTaken = 0;
    }
    // The line still being written: speak whole sentences from it already.
    const partial = lines[lines.length - 1];
    if (!this.inFence && !partial.trim().startsWith("```")) {
      const text = speakableLine(partial);
      let end = 0;
      for (const match of text.matchAll(SENTENCE_END)) end = (match.index ?? 0) + match[0].length;
      if (end > this.partialTaken) {
        this.append(text.slice(this.partialTaken, end), false);
        this.partialTaken = end;
      }
    }
    return this.take(false);
  }

  /** The rest, once the answer is complete. */
  flush(): string[] {
    const chunks = this.take(true);
    if (this.skippedCode && this.emitted) chunks.push("The code is in the chat.");
    return chunks;
  }

  private append(text: string, lineEnd: boolean) {
    if (!text.trim()) return;
    this.pending += (this.pending && !/\s$/.test(this.pending) ? " " : "") + text.trim();
    // A finished line without punctuation (a heading or list item) still ends a thought.
    if (lineEnd && !/[.!?।:;,]$/.test(this.pending)) this.pending += ".";
  }

  private take(all: boolean): string[] {
    const chunks: string[] = [];
    // The first chunk is a single sentence so Sonia starts talking quickly; later chunks are a
    // few sentences, short enough to be voiced while the previous one plays.
    for (;;) {
      const minimum = this.emitted === 0 ? 1 : 200;
      let cut = 0;
      for (const match of this.pending.matchAll(SENTENCE_END)) {
        const end = (match.index ?? 0) + match[0].length;
        if (end > MAX_CHUNK) break;
        cut = end;
        if (end >= minimum) break;
      }
      if (!cut && this.pending.length > MAX_CHUNK) cut = this.pending.lastIndexOf(" ", MAX_CHUNK) || MAX_CHUNK;
      if (!cut || (cut < minimum && !all)) break;
      chunks.push(this.pending.slice(0, cut).trim());
      this.pending = this.pending.slice(cut).trimStart();
      this.emitted++;
    }
    if (all && this.pending.trim()) {
      chunks.push(this.pending.trim());
      this.pending = "";
      this.emitted++;
    }
    return chunks.filter(Boolean);
  }
}

/** Speaks with the device's own voice (always available, no download). */
function speakLocally(text: string, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof speechSynthesis === "undefined") return reject(new Error("This device can't speak replies."));
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = /[ऀ-ॿ]/.test(text) ? "hi-IN" : "en-IN";
    utterance.onend = () => resolve();
    utterance.onerror = event => event.error === "interrupted" || event.error === "canceled"
      ? resolve() : reject(new Error("The reply couldn't be spoken."));
    signal.addEventListener("abort", () => { speechSynthesis.cancel(); resolve(); }, { once: true });
    speechSynthesis.speak(utterance);
  });
}

// --- HD voice: Kokoro running in the browser -------------------------------------------------

/** Kokoro voices for Sonia and Bheem (Kokoro speaks English; Hindi script uses the device voice). */
const KOKORO_VOICES: Record<VoiceChoice, string> = { female: "af_heart", male: "am_michael" };
const PREFERENCE_KEY = "sonia-hd-voice";

export interface HdVoicePlan { phone: boolean; dtype: "fp32" | "q8"; device: "webgpu" | "wasm"; megabytes: number }
export type HdVoiceState =
  | { status: "off" }
  | { status: "downloading"; loaded: number; total: number }
  | { status: "ready" }
  | { status: "failed"; message: string };

export function isPhone(): boolean {
  if (typeof navigator === "undefined") return false;
  const hint = (navigator as Navigator & { userAgentData?: { mobile?: boolean } }).userAgentData?.mobile;
  return hint ?? /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
}

/** Laptops get the full model on the GPU; phones (and computers without WebGPU) the small one. */
export async function hdVoicePlan(): Promise<HdVoicePlan> {
  const phone = isPhone();
  let webgpu = false;
  try {
    const gpu = (navigator as Navigator & { gpu?: { requestAdapter: () => Promise<unknown> } }).gpu;
    webgpu = !phone && !!gpu && !!(await gpu.requestAdapter());
  } catch { webgpu = false; }
  return webgpu
    ? { phone, dtype: "fp32", device: "webgpu", megabytes: 330 }
    : { phone, dtype: "q8", device: "wasm", megabytes: 92 };
}

/** The user's choice on a phone: download the HD voice, or keep the phone's voice. */
export function hdVoicePreference(): "download" | "device" | null {
  try {
    const value = localStorage.getItem(PREFERENCE_KEY);
    return value === "download" || value === "device" ? value : null;
  } catch { return null; }
}
export function setHdVoicePreference(value: "download" | "device") {
  try { localStorage.setItem(PREFERENCE_KEY, value); } catch { /* The choice lasts for this visit. */ }
}

type WorkerReply =
  | { type: "progress"; loaded: number; total: number }
  | { type: "ready" }
  | { type: "load-error"; message: string }
  | { type: "audio"; id: number; blob: Blob; seconds: number; tookSeconds: number }
  | { type: "speak-error"; id: number; message: string };

/** One Kokoro model per page: it stays loaded between voice sessions. */
class HdVoice {
  private worker: Worker | null = null;
  private state: HdVoiceState = { status: "off" };
  private readonly listeners = new Set<(state: HdVoiceState) => void>();
  private readonly pending = new Map<number, { resolve: (blob: Blob) => void; reject: (error: Error) => void }>();
  private nextId = 1;
  private slowChunks = 0;

  get current() { return this.state; }
  /** Generation slower than playback means gaps in speech; such devices use their own voice. */
  get tooSlow() { return this.slowChunks >= 2; }

  subscribe(listener: (state: HdVoiceState) => void) {
    this.listeners.add(listener);
    listener(this.state);
    return () => { this.listeners.delete(listener); };
  }

  private set(state: HdVoiceState) {
    this.state = state;
    this.listeners.forEach(listener => listener(state));
  }

  load(plan: HdVoicePlan) {
    if (this.worker || typeof Worker === "undefined") return;
    this.worker = new Worker(new URL("./kokoro.worker.ts", import.meta.url), { type: "module" });
    this.worker.onmessage = (event: MessageEvent<WorkerReply>) => this.receive(event.data);
    this.worker.onerror = () => this.fail("The HD voice couldn't start on this device.");
    this.set({ status: "downloading", loaded: 0, total: plan.megabytes * 1024 * 1024 });
    this.worker.postMessage({ type: "load", dtype: plan.dtype, device: plan.device });
  }

  private fail(message: string) {
    this.worker?.terminate();
    this.worker = null;
    this.pending.forEach(item => item.reject(new Error(message)));
    this.pending.clear();
    this.set({ status: "failed", message });
  }

  private receive(reply: WorkerReply) {
    if (reply.type === "progress") this.set({ status: "downloading", loaded: reply.loaded, total: reply.total });
    else if (reply.type === "ready") this.set({ status: "ready" });
    else if (reply.type === "load-error") this.fail("The HD voice couldn't be downloaded. Using the device voice.");
    else {
      const item = this.pending.get(reply.id);
      this.pending.delete(reply.id);
      if (!item) return;
      if (reply.type === "audio") {
        if (reply.tookSeconds > reply.seconds * 1.2) this.slowChunks++;
        item.resolve(reply.blob);
      } else item.reject(new Error(reply.message));
    }
  }

  speak(text: string, voice: VoiceChoice): Promise<Blob> {
    if (!this.worker || this.state.status !== "ready") return Promise.reject(new Error("The HD voice isn't ready."));
    const id = this.nextId++;
    return new Promise<Blob>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker!.postMessage({ type: "speak", id, text, voice: KOKORO_VOICES[voice] });
    });
  }
}

export const hdVoice = new HdVoice();

/** Plays spoken chunks in order. Uses the HD voice when it is ready (preparing the next chunk while
 *  the current one plays) and the device's own voice otherwise, so a reply is never lost. */
export class SpeechPlayer {
  private readonly items: { text: string; audio?: Promise<Blob> }[] = [];
  private readonly controller = new AbortController();
  private readonly element = new Audio();
  private finished = false;
  private wake: (() => void) | null = null;
  private readonly running: Promise<void>;

  constructor(private readonly voice: VoiceChoice, private readonly events: {
    onSpeak: (text: string) => void; onError: (error: unknown) => void;
  }) {
    this.running = this.run();
  }

  enqueue(text: string) {
    if (this.controller.signal.aborted || !text.trim()) return;
    this.items.push({ text });
    this.wake?.();
  }

  /** No more chunks are coming; `done` resolves once the last one has played. */
  finish() { this.finished = true; this.wake?.(); }

  done(): Promise<void> { return this.running; }

  stop() {
    this.controller.abort();
    this.element.pause();
    if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
    this.wake?.();
  }

  private useHd(text: string) {
    return hdVoice.current.status === "ready" && !hdVoice.tooSlow && !/[ऀ-ॿ]/.test(text);
  }

  private prepare(index: number) {
    const item = this.items[index];
    if (item && !item.audio && this.useHd(item.text)) {
      item.audio = hdVoice.speak(item.text, this.voice);
      item.audio.catch(() => {}); // handled when its turn to play comes
    }
  }

  private async run() {
    const signal = this.controller.signal;
    for (let index = 0; !signal.aborted; index++) {
      while (index >= this.items.length && !this.finished && !signal.aborted) {
        await new Promise<void>(resolve => { this.wake = resolve; });
        this.wake = null;
      }
      if (signal.aborted || index >= this.items.length) break;
      this.prepare(index);
      this.prepare(index + 1);
      const item = this.items[index];
      let url = "";
      try {
        const audio = item.audio ? await item.audio.catch(() => null) : null;
        if (signal.aborted) break;
        this.events.onSpeak(item.text);
        if (!audio) {
          await speakLocally(item.text, signal);
          continue;
        }
        url = URL.createObjectURL(audio);
        this.element.src = url;
        await new Promise<void>((resolve, reject) => {
          this.element.onended = () => resolve();
          this.element.onerror = () => reject(new Error("The voice reply couldn't be played."));
          signal.addEventListener("abort", () => resolve(), { once: true });
          this.element.play().catch(reject);
        });
      } catch (error) {
        if (!signal.aborted) this.events.onError(error);
        this.controller.abort();
      } finally {
        if (url) URL.revokeObjectURL(url);
      }
    }
    this.element.removeAttribute("src");
  }
}

// --- Listening with the browser's own speech recognition ---------------------------------------

type Recognition = {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
};

function recognitionClass(): (new () => Recognition) | null {
  if (typeof window === "undefined") return null;
  const scope = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

export function browserRecognitionSupported() { return !!recognitionClass(); }

/** The browser can't recognise speech (unsupported, offline, or blocked): use the server instead. */
export class RecognitionUnavailable extends Error {}

/**
 * Listens for one spoken turn with the browser's speech recognition, showing words as they come.
 * Resolves the final text once the user pauses, or null when the session ends.
 */
export function recognizeTurn(signal: AbortSignal, onInterim: (text: string) => void,
  { lang = "en-IN", pauseMs = 700 } = {}): Promise<string | null> {
  const Recognizer = recognitionClass();
  if (!Recognizer) return Promise.reject(new RecognitionUnavailable("Speech recognition isn't available."));
  return new Promise((resolve, reject) => {
    let finalText = "";
    let interim = "";
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let recognition: Recognition | null = null;
    const finish = (value: string | null, error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (recognition) { recognition.onend = null; recognition.onresult = null; recognition.onerror = null; recognition.abort(); }
      if (error) reject(error); else resolve(value);
    };
    const start = () => {
      if (settled || signal.aborted) return;
      recognition = new Recognizer();
      recognition.lang = lang;
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.onresult = event => {
        interim = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) finalText = `${finalText} ${result[0].transcript}`.trim();
          else interim += result[0].transcript;
        }
        onInterim(`${finalText} ${interim}`.trim());
        clearTimeout(timer);
        // A short pause after a finished phrase ends the turn.
        if (finalText && !interim.trim()) timer = setTimeout(() => finish(finalText), pauseMs);
      };
      recognition.onerror = event => {
        if (event.error === "no-speech" || event.error === "aborted") return; // onend restarts
        if (event.error === "not-allowed" || event.error === "service-not-allowed") {
          finish(null, new RecognitionUnavailable("Speech recognition is blocked in this browser."));
        } else finish(null, new RecognitionUnavailable(`Speech recognition failed (${event.error}).`));
      };
      // Chrome ends a session after a stretch of silence: keep listening until the turn is done.
      recognition.onend = () => { if (finalText) finish(finalText); else start(); };
      try { recognition.start(); } catch (error) { finish(null, new RecognitionUnavailable(String(error))); }
    };
    signal.addEventListener("abort", () => finish(null), { once: true });
    start();
  });
}
