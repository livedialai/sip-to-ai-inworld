# Inworld Realtime — Protokolldetails

## Verbindung

```
wss://api.inworld.ai/api/v1/realtime/session?key=<session-key>&protocol=realtime
Authorization: Basic <base64-api-key>
```

- `key` ist ein **frei wählbarer** Session-Bezeichner (z. B. Call-ID), keine API-ID.
- Auth ist `Basic`, **nicht** `Bearer` wie bei OpenAI.
- Das Modell steht **nicht** in der URL, sondern in `session.update`.

## Session-Konfiguration

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "model": "google/gemini-3.1-flash-lite",
    "output_modalities": ["audio"],
    "audio": {
      "input": {
        "format": {"type": "audio/pcmu"},
        "transcription": {"model": "inworld-stt-1"},
        "turn_detection": {"type": "semantic_vad", "create_response": true}
      },
      "output": {
        "model": "inworld-tts-2",
        "voice": "<voice-id>",
        "format": {"type": "audio/pcmu"}
      }
    },
    "instructions": "<prompt>",
    "providerData": {
      "stt": {
        "voice_profile": true,
        "vad_threshold": 0.62,
        "min_end_of_turn_silence": 500,
        "end_of_turn_confidence_threshold": 0.75
      }
    }
  }
}
```

`audio/pcmu` = G.711 μ-law 8 kHz, also Telefonie-Audio ohne Resampling.
`audio/pcm` mit `rate: 24000` funktioniert ebenfalls (dann resampelt der Adapter).

## Ereignisse

Inworld folgt dem OpenAI-Realtime-Schema (GA). Verwendet werden:

```
session.created / session.updated
input_audio_buffer.append            (Audio hoch)
input_audio_buffer.speech_started    (Barge-in)
response.create                      (Antwort anfordern, z. B. Begrüßung)
response.output_audio.delta          (Audio runter)
response.output_audio_transcript.delta/done
conversation.item.input_audio_transcription.delta/completed
response.done
```

## Stimmen

`GET https://api.inworld.ai/tts/v1/voices` (Basic-Auth) liefert alle Stimmen des
Workspace. Clones sind workspace-gebunden; ein Key aus einem anderen Workspace
liefert die Voice-ID nicht und die Session schlägt fehl.

Beispiel: `default-gir-n2kfw-hbdko0a0q9lw__nadine-neu` (Standardstimme "nadine-neu")
vs. `workspace2-md6wv__de-nadine-female` (eigener Clone in Workspace 2) — gleicher
Name, andere Stimme.

## Bekannte Eigenheiten

- Die Begrüßung als `response.create` mit langem `instructions`-Text kann dazu führen,
  dass das Modell den halben Prompt vorliest. Begrüßung kurz halten und als eigenen
  Satz formulieren.
- `providerData` greift ab dem nächsten Audio-Chunk nach `session.update`.
- Ohne `min_end_of_turn_silence` ≥ 400 ms unterbricht sich das Modell bei
  Telefonie-Audio häufig selbst (Echo der Leitung).
