// Realtime voice with Gemini Live: the browser streams the microphone to the model and plays the
// model's voice as it arrives, over one WebSocket. The server only mints the session token (with
// Sonia's setup locked in) and runs the tools the model asks for.

import { runLiveVoiceTool, startLiveVoice, type LiveVoiceStart } from "@/lib/api";

export type LivePhase = "connecting" | "listening" | "thinking" | "speaking";

export interface LiveEvents {
  onPhase: (phase: LivePhase) => void;
  onLevel: (level: number) => void;
  /** What the user is saying, as the model transcribes it. */
  onHeard: (text: string) => void;
  /** What Sonia is saying, as it is spoken. */
  onSaying: (text: string) => void;
  /** A finished exchange, to keep in the chat. */
  onTurn: (user: string, sonia: string) => void;
  /** `fatal`: the session can't continue, so the caller should switch to the standard voice. */
  onError: (message: string, fatal: boolean) => void;
}

const CAPTURE_WORKLET = `
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      const pcm = new Int16Array(channel.length);
      for (let i = 0; i < channel.length; i++) pcm[i] = Math.max(-1, Math.min(1, channel[i])) * 0x7fff;
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor("sonia-capture", Capture);`;

const SEND_SAMPLES_MS = 60;
const MAX_RECONNECTS = 3;

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

function rms(samples: Int16Array): number {
  let sum = 0;
  for (const sample of samples) sum += (sample / 0x8000) ** 2;
  return samples.length ? Math.sqrt(sum / samples.length) : 0;
}

type ServerMessage = {
  setupComplete?: object;
  serverContent?: {
    modelTurn?: { parts?: { inlineData?: { data: string; mimeType?: string } }[] };
    interrupted?: boolean;
    turnComplete?: boolean;
    inputTranscription?: { text?: string };
    outputTranscription?: { text?: string };
  };
  toolCall?: { functionCalls?: { id: string; name: string; args?: Record<string, unknown> }[] };
  toolCallCancellation?: { ids?: string[] };
  goAway?: { timeLeft?: string };
  sessionResumptionUpdate?: { newHandle?: string; resumable?: boolean };
  error?: { message?: string };
};

/** One realtime voice conversation. `start` connects; `stop` ends everything. */
export class LiveVoice {
  private socket: WebSocket | null = null;
  private session: { session_id: string; token: string; url: string } | null = null;
  private handle = "";
  private reconnects = 0;
  private stopped = false;
  private ready = false;
  private stream: MediaStream | null = null;
  private capture: AudioContext | null = null;
  private playback: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private output: GainNode | null = null;
  private pending: Int16Array[] = [];
  private pendingSamples = 0;
  private sampleRate = 16000;
  private playhead = 0;
  private readonly sources = new Set<AudioBufferSourceNode>();
  private heard = "";
  private saying = "";
  private readonly cancelled = new Set<string>();
  private readonly tools = new AbortController();
  private meter: ReturnType<typeof setInterval> | undefined;
  private micLevel = 0;
  private phase: LivePhase = "connecting";
  private muted = false;
  // After a tap-to-interrupt, the rest of that reply is dropped as it arrives.
  private skipReply = false;

  constructor(private readonly details: LiveVoiceStart, private readonly events: LiveEvents) {}

  async start() {
    this.setPhase("connecting");
    // Open the microphone first: if it's blocked there's nothing to connect for.
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.playback = new AudioContext();
    this.output = this.playback.createGain();
    this.analyser = this.playback.createAnalyser();
    this.analyser.fftSize = 512;
    this.output.connect(this.analyser);
    this.analyser.connect(this.playback.destination);
    this.session = await startLiveVoice(this.details, this.tools.signal);
    await this.connect();
    await this.startCapture();
    this.meter = setInterval(() => this.events.onLevel(this.speaking() ? this.outputLevel() : this.micLevel), 80);
  }

  stop() {
    this.stopped = true;
    clearInterval(this.meter);
    this.tools.abort();
    this.flushPlayback();
    this.socket?.close();
    this.stream?.getTracks().forEach(track => track.stop());
    void this.capture?.close().catch(() => {});
    void this.playback?.close().catch(() => {});
  }

  private setPhase(phase: LivePhase) {
    if (phase !== this.phase) { this.phase = phase; this.events.onPhase(phase); }
  }

  private connect(): Promise<void> {
    const session = this.session!;
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(`${session.url}?access_token=${encodeURIComponent(session.token)}`);
      this.socket = socket;
      this.ready = false;
      let opened = false;
      socket.onopen = () => {
        // The token fixes the setup; the client only says whether it is resuming a session.
        socket.send(JSON.stringify({ setup: { sessionResumption: this.handle ? { handle: this.handle } : {} } }));
      };
      socket.onmessage = async event => {
        const text = typeof event.data === "string" ? event.data : await (event.data as Blob).text();
        const message = JSON.parse(text) as ServerMessage;
        if (message.setupComplete) {
          opened = true;
          this.ready = true;
          this.reconnects = 0;
          this.setPhase("listening");
          resolve();
          return;
        }
        this.receive(message);
      };
      socket.onclose = event => {
        this.ready = false;
        if (!opened) {
          reject(new Error(event.reason || "Realtime voice couldn't connect."));
          return;
        }
        if (this.stopped) return;
        // Connections last about ten minutes; carry on in a new one with the same conversation.
        if (this.handle && this.reconnects < MAX_RECONNECTS) {
          this.reconnects++;
          this.connect().catch(() => this.events.onError("Realtime voice disconnected.", true));
        } else {
          this.events.onError(event.reason || "Realtime voice disconnected.", true);
        }
      };
    });
  }

  private async startCapture() {
    this.capture = new AudioContext({ sampleRate: 16000 });
    this.sampleRate = this.capture.sampleRate;
    const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: "application/javascript" }));
    try { await this.capture.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
    const node = new AudioWorkletNode(this.capture, "sonia-capture");
    node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => this.sendAudio(new Int16Array(event.data));
    this.capture.createMediaStreamSource(this.stream!).connect(node);
  }

  private sendAudio(samples: Int16Array) {
    this.micLevel = rms(samples);
    this.pending.push(samples);
    this.pendingSamples += samples.length;
    if (this.pendingSamples < (this.sampleRate * SEND_SAMPLES_MS) / 1000) return;
    const joined = new Int16Array(this.pendingSamples);
    let offset = 0;
    for (const chunk of this.pending) { joined.set(chunk, offset); offset += chunk.length; }
    this.pending = [];
    this.pendingSamples = 0;
    if (this.muted || !this.ready || this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ realtimeInput: { audio: {
      data: toBase64(new Uint8Array(joined.buffer)), mimeType: `audio/pcm;rate=${this.sampleRate}`,
    } } }));
  }

  private receive(message: ServerMessage) {
    if (message.sessionResumptionUpdate?.resumable && message.sessionResumptionUpdate.newHandle) {
      this.handle = message.sessionResumptionUpdate.newHandle;
    }
    if (message.error) this.events.onError(message.error.message || "Realtime voice failed.", false);
    if (message.toolCallCancellation?.ids) message.toolCallCancellation.ids.forEach(id => this.cancelled.add(id));
    if (message.toolCall?.functionCalls?.length) void this.runTools(message.toolCall.functionCalls);
    const content = message.serverContent;
    if (!content) return;
    if (content.inputTranscription?.text) {
      this.heard += content.inputTranscription.text;
      this.events.onHeard(this.heard.trim());
      if (!this.speaking()) this.setPhase("thinking");
    }
    if (content.outputTranscription?.text) {
      this.saying += content.outputTranscription.text;
      this.events.onSaying(this.saying.trim());
    }
    for (const part of content.modelTurn?.parts ?? []) {
      if (part.inlineData?.data && !this.skipReply) this.play(part.inlineData.data, part.inlineData.mimeType);
    }
    if (content.interrupted) this.flushPlayback();
    if (content.turnComplete || content.interrupted) {
      this.skipReply = false;
      if (this.heard.trim() || this.saying.trim()) this.events.onTurn(this.heard.trim(), this.saying.trim());
      this.heard = "";
      this.saying = "";
    }
  }

  private async runTools(calls: { id: string; name: string; args?: Record<string, unknown> }[]) {
    this.setPhase("thinking");
    const responses = await Promise.all(calls.map(async call => {
      let result: string;
      try { result = await runLiveVoiceTool(this.session!.session_id, call.name, call.args ?? {}, this.tools.signal); }
      catch (error) { result = `The tool failed: ${error instanceof Error ? error.message : "unknown error"}. Say so briefly.`; }
      return { id: call.id, name: call.name, response: { result } };
    }));
    const live = responses.filter(response => !this.cancelled.has(response.id));
    if (live.length && this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ toolResponse: { functionResponses: live } }));
    }
  }

  private play(base64: string, mimeType = "") {
    const context = this.playback!;
    if (context.state === "suspended") void context.resume();
    const rate = Number(/rate=(\d+)/.exec(mimeType)?.[1] ?? 24000);
    const bytes = Uint8Array.from(atob(base64), character => character.charCodeAt(0));
    const samples = new Int16Array(bytes.buffer, 0, bytes.length >> 1);
    const buffer = context.createBuffer(1, samples.length, rate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 0x8000;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.output!);
    this.playhead = Math.max(this.playhead, context.currentTime + 0.03);
    source.start(this.playhead);
    this.playhead += buffer.duration;
    this.sources.add(source);
    this.setPhase("speaking");
    source.onended = () => {
      this.sources.delete(source);
      if (!this.sources.size && !this.stopped) this.setPhase("listening");
    };
  }

  private flushPlayback() {
    this.sources.forEach(source => { source.onended = null; try { source.stop(); } catch { /* already ended */ } });
    this.sources.clear();
    this.playhead = 0;
    if (!this.stopped) this.setPhase("listening");
  }

  private speaking() { return this.sources.size > 0; }

  private outputLevel(): number {
    if (!this.analyser) return 0;
    const data = new Float32Array(this.analyser.fftSize);
    this.analyser.getFloatTimeDomainData(data);
    let sum = 0;
    for (const value of data) sum += value * value;
    return Math.sqrt(sum / data.length);
  }

  /** Ends Sonia's current reply right away (the user tapped the orb). */
  interrupt() {
    this.skipReply = true;
    this.flushPlayback();
  }

  /** Pauses the microphone: nothing is sent while muted. */
  setMuted(muted: boolean) {
    this.muted = muted;
    if (muted && this.ready && this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ realtimeInput: { audioStreamEnd: true } }));
    }
  }
}
