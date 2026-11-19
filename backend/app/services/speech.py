"""Voice mode on the server: Groq Whisper turns speech into text.

Only browsers without built-in speech recognition use this; the reply is spoken in the browser
(Kokoro or the device's own voice), so there is no text-to-speech here. The answer itself still comes
from the normal chat pipeline (documents, tools, memory, citations).
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo").strip()
# Whisper guesses the language from the audio, and on a short or noisy clip it can guess wrong
# (a two-word "hi Sonia" came back as Korean). Sonia's users speak these languages; anything else
# is transcribed again in the fallback language. Names are as Whisper reports them.
VOICE_LANGUAGES = {name.strip().lower() for name in
                   os.getenv("VOICE_LANGUAGES", "english,hindi").split(",") if name.strip()}
VOICE_FALLBACK_LANGUAGE = os.getenv("VOICE_FALLBACK_LANGUAGE", "en").strip()
# A short sample of how users talk. Whisper follows the prompt's style, so Roman-script Hinglish
# stays in Roman script instead of switching to Devanagari.
VOICE_PROMPT = os.getenv("VOICE_PROMPT", "Hi Sonia. Namaste Sonia, is PDF ka summary batao. "
                                         "Please explain this in simple words.").strip()
# Segments Whisper itself rates as probably not speech (background noise) are dropped.
NO_SPEECH_THRESHOLD = 0.6

class SpeechUnavailable(RuntimeError):
    """The speech provider is not configured, out of quota or down."""


def transcription_configured() -> bool:
    return bool(GROQ_API_KEY and STT_MODEL)


def _transcription(audio: bytes, filename: str, content_type: str, language: str | None) -> dict:
    data = {"model": STT_MODEL, "response_format": "verbose_json", "temperature": "0"}
    if VOICE_PROMPT:
        data["prompt"] = VOICE_PROMPT
    if language:
        data["language"] = language
    try:
        response = requests.post(
            GROQ_STT_URL, headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": (filename, audio, content_type)}, data=data, timeout=(10, 60))
    except (requests.ConnectionError, requests.Timeout) as error:
        raise SpeechUnavailable("The speech service could not be reached.") from error
    if response.status_code >= 400:
        # Provider bodies stay in the logs; the user gets a plain message.
        logger.warning("Transcription failed (HTTP %s): %s", response.status_code, response.text[:300])
        raise SpeechUnavailable("Your voice couldn't be transcribed right now.")
    return response.json()


def _spoken_text(result: dict) -> str:
    segments = result.get("segments")
    if isinstance(segments, list) and segments:
        kept = [str(segment.get("text") or "") for segment in segments
                if not (isinstance(segment.get("no_speech_prob"), (int, float))
                        and segment["no_speech_prob"] > NO_SPEECH_THRESHOLD)]
        return " ".join(part.strip() for part in kept if part.strip())
    return str(result.get("text") or "").strip()


def transcribe(audio: bytes, filename: str, content_type: str) -> str:
    if not transcription_configured():
        raise SpeechUnavailable("Voice input is not configured on this server.")
    result = _transcription(audio, filename, content_type, None)
    language = str(result.get("language") or "").strip().lower()
    if VOICE_LANGUAGES and language and language not in VOICE_LANGUAGES and VOICE_FALLBACK_LANGUAGE:
        logger.info("Whisper heard %s; transcribing again in %s", language, VOICE_FALLBACK_LANGUAGE)
        result = _transcription(audio, filename, content_type, VOICE_FALLBACK_LANGUAGE)
    return _spoken_text(result)
