# sip-to-ai-inworld

SIP/RTP-Bridge zu **Inworld Realtime** — ein Fork von
[aicc2025/sip-to-ai](https://github.com/aicc2025/sip-to-ai) (Apache-2.0) mit einem
zusätzlichen Provider.

```
Telefonie (G.711 μ-law, 8 kHz)  ──►  dieser Adapter  ──►  Inworld Realtime (WSS)
                                  ◄──                ◄──
```

## Warum dieser Fork

Upstream unterstützt OpenAI Realtime, Deepgram Voice Agent, Gemini Live und Grok Voice.
**Inworld fehlte** — und Inworld ist mit **0,98–1,58 ct/min** der günstigste
Realtime-Stack am Markt (Deepgram: 7,5 ct/min, Gemini Live: 1,4–4 ct/min).

Inworld spricht das OpenAI-Realtime-Protokoll. Der Unterschied sind vier Stellen:
URL, Authentifizierung, Modell/Stimme in `session.update` und `providerData`.

## Schnellstart

```bash
git clone <repo> && cd sip-to-ai-inworld
uv venv && source .venv/bin/activate
uv sync

cp .env.example .env      # INWORLD_API_KEY eintragen
uv run python -m app.main
```

Der Adapter lauscht dann auf `SIP_DOMAIN:SIP_PORT` (Standard `5060/udp`) und nimmt
INVITEs an. Getestet mit einer RustPBX (rustpbx 0.5.0) als Gegenstelle und G.711 μ-law
durchgereicht — **kein Resampling**.

## Konfiguration (Inworld)

| Variable | Bedeutung | Beispiel |
|---|---|---|
| `AI_VENDOR` | Provider | `inworld` |
| `INWORLD_API_KEY` | Basic-Key (Base64) aus dem Inworld-Portal | `…` |
| `INWORLD_WS_ENDPOINT` | Realtime-Endpunkt | `wss://api.inworld.ai/api/v1/realtime/session` |
| `INWORLD_MODEL` | LLM hinter Inworld | `google/gemini-3.1-flash-lite` |
| `INWORLD_VOICE` | Voice-ID (siehe unten) | `default-gir-…__nadine-neu` |
| `INWORLD_TTS_MODEL` | TTS | `inworld-tts-2` |
| `INWORLD_STT_MODEL` | STT | `inworld-stt-1` |
| `INWORLD_VAD_THRESHOLD` | VAD-Schwelle | `0.62` |
| `INWORLD_MIN_END_OF_TURN_SILENCE` | Stille bis Turn-Ende (ms) | `500` |
| `INWORLD_END_OF_TURN_CONFIDENCE` | Konfidenz für Turn-Ende | `0.75` |

Vollständige Liste: `.env.example`.

### Voice-IDs

Stimmen sind **workspace-gebunden**. Ein Key aus Workspace A sieht die Clones aus
Workspace B nicht. Welche Stimme zu einem Key gehört:

```bash
curl -s -H "Authorization: Basic $INWORLD_API_KEY" \
  https://api.inworld.ai/tts/v1/voices | jq -r '.voices[] | select(.languages[]=="de") | .voiceId'
```

## Was der Fork ändert

| Datei | Änderung |
|---|---|
| `app/ai/inworld_realtime.py` | **neu** — `InworldRealtimeClient`, erbt vom OpenAI-Client |
| `app/ai/openai_realtime.py` | `_build_ws_url()` als überschreibbare Methode (vorher inline) |
| `app/config.py` | `INWORLD_*`-Felder, `inworld` in der Vendor-Liste |
| `app/main.py` | Vendor-Zweig `inworld` in `create_ai_client()` |

Der Rest — SIP-Stack, RTP, Ringpuffer, Barge-in, Health-Checks — ist unverändert
von Upstream.

## Messwerte (RustPBX → Adapter → Inworld, 06.11.2026)

```
INVITE                    → 200 OK            0,38 s
session.updated           → erster Ton        0,53 s
Anrufbeginn               → erster Ton        0,91 s
Barge-in                  speech_started      Puffer verworfen, Ausgabe gestoppt
Audio                     G.711 μ-law 8 kHz   durchgereicht, kein Resampling
```

## Was fehlt (bewusst nicht enthalten)

- **Tool-Calls** (`tools`, `tool_choice`, `function_call`) — Upstream hat keine,
  Inworld kann sie. Das ist der nächste Schritt.
- **Transfer** (SIP `REFER`) — muss die PBX machen oder hier ergänzt werden.
- **Mandanten/DID-Auflösung** — ein Adapter bedient alle Anrufe gleich.
- **Aufzeichnung**.

## Aufbau

```
app/
  main.py                 Start, Vendor-Auswahl
  config.py               Konfiguration (.env)
  ai/
    duplex_base.py        gemeinsame Basis (Queues, Events, Reconnect)
    openai_realtime.py    OpenAI Realtime (Upstream)
    inworld_realtime.py   Inworld Realtime (dieser Fork)
  sip_async/              SIP + RTP (Upstream, unverändert)
  bridge/                 Audio-Bridge, Session-Logik
docs/
  inworld.md              Details zum Inworld-Protokoll
  upstream/               Original-Dokumentation
```

## Lizenz und Herkunft

Apache-2.0, siehe `LICENSE`. Basiert auf
[aicc2025/sip-to-ai](https://github.com/aicc2025/sip-to-ai); die Inworld-Ergänzung
stammt von Weser-AI. Upstream-Dokumentation liegt unter `docs/upstream/`.
