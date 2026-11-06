"""Inworld Realtime client.

Inworld folgt dem OpenAI-Realtime-Protokoll. Unterschiede zu OpenAI:
  * URL:  wss://api.inworld.ai/api/v1/realtime/session?key=<session>&protocol=realtime
  * Auth: Authorization: Basic *** key>   (Bearer wird ebenfalls akzeptiert)
  * Modell/Stimme/providerData stehen in session.update, nicht in der URL

Zusatz: Tool-Calls (function_call) werden an einen ToolRunner gegeben und das
Ergebnis als function_call_output zurueckgespielt.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

import structlog

from app.ai.openai_realtime import OpenAIRealtimeClient

logger = structlog.get_logger(__name__)


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
        tools: Optional[list] = None,
        tool_runner: Any = None,
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
        self._tools = tools or []
        self._tool_runner = tool_runner
        self._handled_calls: set[str] = set()

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

        # Tools
        if self._tools and self._tool_runner is not None:
            session["tools"] = self._tools
            session["tool_choice"] = "auto"
        return cfg

    async def _on_provider_event(self, msg_type: str, data: Dict[str, Any]) -> None:
        """Fuehrt Tool-Calls aus und antwortet mit function_call_output."""
        if self._tool_runner is None:
            return

        call: Optional[Dict[str, Any]] = None
        if msg_type == "response.function_call_arguments.done":
            call = {
                "call_id": data.get("call_id"),
                "name": data.get("name"),
                "arguments": data.get("arguments") or "{}",
            }
        elif msg_type == "response.output_item.done":
            item = data.get("item") or {}
            if item.get("type") == "function_call":
                call = {
                    "call_id": item.get("call_id"),
                    "name": item.get("name"),
                    "arguments": item.get("arguments") or "{}",
                }
        if not call or not call.get("call_id") or not call.get("name"):
            return
        if call["call_id"] in self._handled_calls:
            return
        self._handled_calls.add(call["call_id"])

        try:
            args = json.loads(call["arguments"]) if isinstance(call["arguments"], str) else {}
        except json.JSONDecodeError:
            args = {}

        logger.info("tool-call", name=call["name"], args=args)
        try:
            result = await self._tool_runner(call["name"], args)
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool runner failed", error=str(exc), name=call["name"])
            result = {"fehler": str(exc)}

        output = json.dumps(result, ensure_ascii=False)
        logger.info("tool-result", name=call["name"], result=output[:400])
        await self._ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": output,
                    },
                }
            )
        )
        await self._ws.send(json.dumps({"type": "response.create"}))
