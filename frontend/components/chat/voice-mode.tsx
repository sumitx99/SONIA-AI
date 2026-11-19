"use client";

import { useEffect, useRef, useState } from "react";
import { Download, Mic, MicOff, X } from "lucide-react";
import { handleApiError, transcribeAudio, voiceStatus, type LiveVoiceStart, type VoiceChoice } from "@/lib/api";
import { LiveVoice } from "@/lib/live-voice";
import {
  Microphone, RecognitionUnavailable, SpeechChunker, SpeechPlayer, browserRecognitionSupported, hdVoice, hdVoicePlan,
  hdVoicePreference, recognizeTurn, setHdVoicePreference, voiceSupported, type HdVoicePlan, type HdVoiceState,
} from "@/lib/voice";
import styles from "@/components/chat/voice-mode.module.css";

type Phase = "starting" | "listening" | "transcribing" | "thinking" | "speaking" | "paused" | "error";

const phaseLabel: Record<Phase, string> = {
  starting: "Getting ready…",
  listening: "Listening",
  transcribing: "Got it…",
  thinking: "Thinking…",
  speaking: "Speaking · start talking to interrupt",
  paused: "Microphone paused",
  error: "Voice mode stopped",
};

const VOICE_KEY = "sonia-voice";
// The two voices, by name: Sonia (female) and Bheem (male).
const voiceNames: Record<VoiceChoice, string> = { female: "Sonia", male: "Bheem" };

export interface VoiceModeProps {
  /** Ask Sonia through the normal chat flow. `onText` receives the answer text as it streams.
   *  Resolves once the answer is finished (false if it failed or was stopped). */
  onAsk: (query: string, voice: VoiceChoice, onText: (raw: string) => void) => Promise<boolean>;
  /** Stop the answer that is being written (the user interrupted). */
  onStop: () => void;
  onClose: () => void;
  context?: string;
  /** Realtime voice (Gemini Live): what the session should know, and where finished exchanges go. */
  live?: {
    details: () => Omit<LiveVoiceStart, "voice">;
    onTurn: (user: string, sonia: string) => void;
  };
}

function savedVoice(): VoiceChoice {
  try {
    const saved = localStorage.getItem(VOICE_KEY);
    if (saved === "male" || saved === "female") return saved;
  } catch { /* Browser storage is optional. */ }
  return "female";
}

/**
 * ChatGPT-style voice conversation. Realtime (Gemini Live: speech in, speech out) when available;
 * otherwise the standard voice (listen → answer → speak) takes over, so voice never just stops.
 */
export function VoiceMode({ onAsk, onStop, onClose, context, live }: VoiceModeProps) {
  const [engine, setEngine] = useState<"live" | "standard">(live ? "live" : "standard");
  const [phase, setPhase] = useState<Phase>("starting");
  const [level, setLevel] = useState(0);
  const [heard, setHeard] = useState("");
  const [saying, setSaying] = useState("");
  const [notice, setNotice] = useState("");
  const [voice, setVoice] = useState<VoiceChoice>(savedVoice);
  const [muted, setMuted] = useState(false);
  const [hd, setHd] = useState<HdVoiceState>(hdVoice.current);
  const [plan, setPlan] = useState<HdVoicePlan | null>(null);
  // On a phone the HD voice is a choice (it's a download); this asks once.
  const [askDownload, setAskDownload] = useState(false);
  const voiceRef = useRef(voice);
  const mutedRef = useRef(muted);
  const callbacks = useRef({ onAsk, onStop, live });
  const liveSession = useRef<LiveVoice | null>(null);
  const interrupt = useRef<() => void>(() => {});
  const stopListening = useRef<() => void>(() => {});
  voiceRef.current = voice;
  mutedRef.current = muted;
  callbacks.current = { onAsk, onStop, live };

  useEffect(() => hdVoice.subscribe(setHd), []);

  // The HD voice is only for the standard voice; realtime voice speaks for itself.
  useEffect(() => {
    if (engine !== "standard") return;
    let active = true;
    void hdVoicePlan().then(found => {
      if (!active) return;
      setPlan(found);
      const preference = hdVoicePreference();
      if (!found.phone || preference === "download") hdVoice.load(found);
      else if (preference === null) setAskDownload(true);
    });
    return () => { active = false; };
  }, [engine]);

  // Realtime voice. Changing the voice starts a new session (the voice is part of its setup).
  useEffect(() => {
    const setup = callbacks.current.live;
    if (engine !== "live" || !setup) return;
    let ended = false;
    setPhase("starting");
    setNotice("");
    const session = new LiveVoice({ ...setup.details(), voice }, {
      onPhase: next => { if (!ended) setPhase(next === "connecting" ? "starting" : next); },
      onLevel: value => { if (!ended) setLevel(value); },
      onHeard: text => { if (!ended) setHeard(text); },
      onSaying: text => { if (!ended) setSaying(text); },
      onTurn: (user, sonia) => callbacks.current.live?.onTurn(user, sonia),
      onError: (message, fatal) => {
        if (ended) return;
        if (fatal) { ended = true; session.stop(); setNotice("Realtime voice isn’t available right now, so the standard voice is on."); setEngine("standard"); }
        else setNotice(message);
      },
    });
    liveSession.current = session;
    interrupt.current = () => session.interrupt();
    session.setMuted(mutedRef.current);
    session.start().catch(error => {
      if (ended) return;
      ended = true;
      session.stop();
      if (error instanceof DOMException && error.name === "NotAllowedError") {
        setNotice("Microphone access is blocked. Allow it in your browser’s site settings, then try again.");
        setPhase("error");
        return;
      }
      setNotice("Realtime voice isn’t available right now, so the standard voice is on.");
      setEngine("standard");
    });
    return () => {
      ended = true;
      session.stop();
      liveSession.current = null;
      interrupt.current = () => {};
    };
  }, [engine, voice]);

  function downloadHd() {
    if (!plan) return;
    setHdVoicePreference("download");
    setAskDownload(false);
    hdVoice.load(plan);
  }

  function chooseVoice(next: VoiceChoice) {
    setVoice(next);
    try { localStorage.setItem(VOICE_KEY, next); } catch { /* Keep the choice for this session. */ }
  }

  // The standard voice: listen in the browser, answer through the chat, speak in the browser.
  useEffect(() => {
    if (engine !== "standard") return;
    const session = new AbortController();
    const signal = session.signal;
    let microphone: Microphone | null = null;
    const fail = (message: string) => { if (!signal.aborted) { setNotice(message); setPhase("error"); } };

    (async () => {
      if (!voiceSupported()) return fail("This browser can’t use the microphone. Try a recent Chrome, Edge or Safari.");
      // The browser recognises speech itself when it can (instant, free); the server (Whisper)
      // is the fallback for browsers without it.
      let useServer = !browserRecognitionSupported();
      if (useServer) {
        try {
          if (!(await voiceStatus()).transcription) return fail("Voice input isn’t available in this browser. Try Chrome or Edge.");
        } catch (error) { return fail(handleApiError(error)); }
      }
      try {
        microphone = await Microphone.open();
      } catch (error) {
        return fail(error instanceof DOMException && error.name === "NotAllowedError"
          ? "Microphone access is blocked. Allow it in your browser’s site settings, then try again."
          : "No microphone could be opened.");
      }
      if (signal.aborted) { microphone.close(); return; }

      while (!signal.aborted) {
        if (mutedRef.current) { setPhase("paused"); await new Promise(resolve => setTimeout(resolve, 200)); continue; }
        setPhase("listening");
        const listening = new AbortController();
        const endListening = () => listening.abort();
        stopListening.current = endListening;
        signal.addEventListener("abort", endListening, { once: true });
        let text = "";
        try {
          if (!useServer) {
            const mic = microphone;
            const meter = setInterval(() => setLevel(mic.level()), 80);
            try { text = (await recognizeTurn(listening.signal, interim => setHeard(interim))) ?? ""; }
            finally { clearInterval(meter); setLevel(0); }
          } else {
            const recording = await microphone.record(listening.signal, value => setLevel(value));
            if (recording && !signal.aborted) {
              setPhase("transcribing");
              text = await transcribeAudio(recording, signal);
            }
          }
        } catch (error) {
          if (signal.aborted) break;
          if (error instanceof RecognitionUnavailable) {
            useServer = true;  // e.g. offline or blocked: keep going with the server
            continue;
          }
          setNotice(handleApiError(error));
          continue;
        } finally {
          signal.removeEventListener("abort", endListening);
          stopListening.current = () => {};
        }
        text = text.trim();
        if (!text || signal.aborted) continue;
        setNotice("");
        setHeard(text);
        setSaying("");
        setPhase("thinking");

        const turn = new AbortController();
        const endTurn = () => turn.abort();
        signal.addEventListener("abort", endTurn, { once: true });
        let interrupted = false;
        const player = new SpeechPlayer(voiceRef.current, {
          onSpeak: sentence => { setSaying(sentence); setPhase("speaking"); },
          onError: error => setNotice(`${handleApiError(error)} The answer is in the chat.`),
        });
        const stopTurn = () => {
          if (interrupted) return;
          interrupted = true;
          player.stop();
          callbacks.current.onStop();
          turn.abort();
        };
        interrupt.current = stopTurn;
        // Talking over Sonia (or tapping the orb) stops the answer and starts listening again.
        void microphone.waitForSpeech(turn.signal).then(spoke => { if (spoke) stopTurn(); });
        const chunker = new SpeechChunker();
        await callbacks.current.onAsk(text, voiceRef.current, raw => {
          if (interrupted) return;
          const chunks = chunker.push(raw);
          // Show the reply as soon as it is written, before its audio is ready.
          if (chunks.length) setSaying(current => current || chunks[0]);
          chunks.forEach(chunk => player.enqueue(chunk));
        });
        if (!interrupted) {
          chunker.flush().forEach(chunk => player.enqueue(chunk));
          player.finish();
          await player.done();
        }
        interrupt.current = () => {};
        turn.abort();
        signal.removeEventListener("abort", endTurn);
        setSaying("");
      }
    })();

    return () => {
      session.abort();
      interrupt.current();
      microphone?.close();
    };
  }, [engine]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const shown: Phase = muted && phase !== "error" && phase !== "starting" ? "paused" : phase;
  const busy = phase === "thinking" || phase === "speaking";
  return <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="Voice mode">
    <div className={styles.top}>
      <span className={styles.context}>{context || "Voice mode"}</span>
      <div className={styles.voices} role="radiogroup" aria-label="Voice">
        {(["female", "male"] as const).map(option => <button key={option} type="button" role="radio"
          aria-checked={voice === option} className={styles.voiceOption} onClick={() => chooseVoice(option)}>
          {voiceNames[option]}</button>)}
      </div>
    </div>

    <div className={styles.stage}>
      <button type="button" className={styles.orb} data-phase={shown}
        style={{ "--level": Math.min(1, level * 6).toFixed(3) } as React.CSSProperties}
        aria-label={busy ? "Stop Sonia and talk" : phaseLabel[shown]}
        onClick={() => { if (busy) interrupt.current(); }}>
        <span className={styles.orbCore} />
      </button>
      <p className={styles.phase} aria-live="polite">{phaseLabel[shown]}</p>
      <div className={styles.captions}>
        {heard && <p className={styles.heard}>{heard}</p>}
        {saying && <p className={styles.saying}>{saying}</p>}
      </div>
      {notice && <p className={styles.notice} role="status">{notice}</p>}
    </div>

    {engine === "standard" && askDownload && plan && <div className={styles.downloadCard} role="region" aria-label="HD voice">
      <div>
        <strong>Download Sonia’s HD voice?</strong>
        <span>About {plan.megabytes} MB, one time. Best on Wi-Fi. Until then your phone’s voice speaks.</span>
      </div>
      <div className={styles.downloadActions}>
        <button type="button" className={styles.secondaryButton}
          onClick={() => { setHdVoicePreference("device"); setAskDownload(false); }}>Use phone voice</button>
        <button type="button" className={styles.primaryButton} onClick={downloadHd}><Download size={14} />Download</button>
      </div>
    </div>}

    <div className={styles.voiceStatus} aria-live="polite">
      {engine === "live" ? <span>Realtime voice</span>
        : hd.status === "downloading" ? <>
        <span>Downloading HD voice · {Math.round(hd.loaded / 1048576)} / {Math.max(1, Math.round(hd.total / 1048576))} MB</span>
        <span className={styles.progress}><span style={{ width: `${hd.total ? Math.min(100, (hd.loaded / hd.total) * 100) : 0}%` }} /></span>
      </> : hd.status === "ready" ? <span>HD voice</span>
        : hd.status === "failed" ? <span>{hd.message}</span>
        : plan?.phone && !askDownload ? <button type="button" className={styles.linkButton} onClick={downloadHd}>
            Phone voice · Download HD voice ({plan.megabytes} MB)</button>
        : null}
    </div>

    <div className={styles.controls}>
      <button type="button" className={styles.control} data-active={muted} disabled={phase === "error" || phase === "starting"}
        aria-label={muted ? "Turn microphone on" : "Pause microphone"} onClick={() => {
          // The loop reads the ref, so update it now rather than on the next render.
          mutedRef.current = !muted;
          liveSession.current?.setMuted(!muted);
          if (!muted) stopListening.current();
          setMuted(!muted);
        }}>
        {muted ? <MicOff size={20} /> : <Mic size={20} />}
      </button>
      <button type="button" className={`${styles.control} ${styles.end}`} aria-label="End voice mode" onClick={onClose}>
        <X size={22} />
      </button>
    </div>
  </div>;
}
