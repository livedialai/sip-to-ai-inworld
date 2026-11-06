"""Inworld Realtime client.

Inworld folgt dem OpenAI-Realtime-Protokoll. Unterschiede zu OpenAI:
  * URL:  wss://api.inworld.ai/api/v1/realtime/session?key=<session>&protocol=realtime
  * Auth: Authorization: Basic <base64 key>   (nicht Bearer)
  * Modell/Stimme/providerData stehen in session.update, nicht in der URL
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from app.ai.openai_realtime import OpenAIRealtimeClient


class InworldRealtimeClient(OpenAIRealtimeClient):
    """Inworld Realtime API client (OpenAI-kompatibles Protokoll)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "google/gemini-3.1-flash-lite",
        voice: str = "",
        ws_endpoint: str = "wss://api.inworld.ai/api/v1/realtime/session",
        instructions: str = "You are a helpful assistant.",
        greeting: Optional[str] = None,
        audio_format: str = "pcmu",
        tts_model: str = "inworld-tts-2",
        stt_model: str = "inworld-stt-1",
        provider_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            voice=voice,
            ws_endpoint=ws_endpoint,
            instructions=instructions,
            greeting=greeting,
            audio_format=audio_format,
            noise_reduction="none",
        )
        self._tts_model = tts_model
        self._stt_model = stt_model
        self._session_key = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        self._provider_data = provider_data or {
            "stt": {
                "voice_profile": True,
                "vad_threshold": 0.62,
                "min_end_of_turn_silence": 500,
                "end_of_turn_confidence_threshold": 0.75,
            }
        }

    def _build_ws_url(self) -> str:
        sep = "&" if "?" in self._ws_url else "?"
        return f"{self._ws_url}{sep}key={self._session_key}&protocol=realtime"

    def _build_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Basic {self._api_key}"}

    def _build_session_config(self) -> Dict[str, Any]:
        cfg = super()._build_session_config()
        session = cfg["session"]
        session["model"] = self._model

        audio = session.setdefault("audio", {})
        out = audio.setdefault("output", {})
        out["model"] = self._tts_model
        if self._voice:
            out["voice"] = self._voice
        inp = audio.setdefault("input", {})
        if self._stt_model:
            inp["transcription"] = {"model": self._stt_model}

        # Inworld-Erweiterungen
        session["providerData"] = self._provider_data
        return cfg
