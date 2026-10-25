# JalRekha Volunteer — Volunteer-Report Flow

## 1. Overview

JalRekha Volunteer is the volunteer-facing half of the JalRekha submission. Its user is a Defensa Civil municipal volunteer in Argentina's Litoral region, today coordinating flood and storm reports over WhatsApp audio messages that pile up in a single chat and are triaged by hand. JalRekha Volunteer replaces that pipeline with a structured intake: a PWA (or Android app) captures audio, photo, and an optional typed transcript, ships it to a backend that parses it into a `ParsedObservation`, fuses it with the site's camera-derived signals into a `FusedAlert`, and — when the alert is orange or red — lets Gemma 4 emit tool calls that drive local actuators (alarm, radio, push notification). Unlike a WhatsApp thread, every report is timestamped, geo-tagged to a site, machine-parseable, and queueable while offline.

## 2. End-to-end data flow

```mermaid
sequenceDiagram
    participant V as Volunteer
    participant UI as PWA / Android UI
    participant Q as IndexedDB / Room queue
    participant API as POST /api/reports
    participant ASR as asr_client (Whisper tiny)
    participant STR as GemmaFewShotTextStructurer
    participant FUSE as recompute_site_alert
    participant ACT as dispatch_actuators (Gemma tool selection)
    participant BG as BackgroundTask image_assessor

    V->>UI: select site, record audio, attach photo, type optional transcript
    alt Offline
        UI->>Q: enqueue report
        Q-->>UI: stored locally
        Note over Q,API: flushes on reconnect
    else Online (Android only, on-device path)
        UI->>UI: GemmaOnDevice.structureReport (parser_source=gemma-android)
        UI-->>V: show ParsedObservation without backend round-trip
    end
    UI->>API: multipart (transcript_text, photo, audio, reporter_name, reporter_role, offline_created)
    API->>API: persist_upload(photo), persist_upload(audio)
    alt transcript empty and audio present
        API->>ASR: transcribe(audio_path)
        ASR-->>API: transcript_text
    end
    API->>STR: structure_report(transcript_text)
    STR-->>API: ParsedObservation (parser_source=llm or rules)
    API->>FUSE: recompute_site_alert(site, parsed)
    FUSE-->>API: FusedAlert(level, score, reasoning)
    alt level in {orange, red} and actuators enabled
        API->>ACT: dispatch_actuators(alert, runtime)
        ACT-->>API: tool_calls fired (trigger_alarm, notify_app, ...)
        API->>API: append "actuated: ..." to decision_trace
    end
    alt photo present and JALREKHA_VOLUNTEER_IMAGE_ENABLED
        API->>BG: schedule image_assessor.assess(photo_path)
        BG-->>API: append "image_description: ..." and "image_flags: ..." to decision_trace
    end
    API-->>UI: {report, parsed, alert}
```

Routing entry point: `backend/src/jalrekha/api/routers/volunteer.py`.

## 3. The `parser_source` field

| Value | Where it's set | What it means |
|---|---|---|
| `"rules"` | `services/report_structuring._fallback_parse` | Deterministic keyword parser. Used when the LLM is unreachable or returns unparseable JSON. Always available. |
| `"llm"` | `services/report_structuring._normalize_llm_payload` | Gemma 4 via Ollama on the backend host (`GemmaFewShotTextStructurer` with the rioplatense few-shot corpus). Default when Ollama is reachable. |
| `"gemma-android"` | `ui/MainViewModel.submitReport` (Android) | Gemma 4 running on-device via LiteRT-LM Android. Set when `gemma-4-E2B-it.litertlm` is present in `context.filesDir` and `structureReport` returned valid JSON. No silent fallback to the backend on failure — the operator sees the error and can retry. |

The Android UI surfaces this field as a small chip next to the parsed observation, with Spanish labels chosen so a volunteer in the field can reason about provenance without reading logs:

- `"Analizado con Gemma en este dispositivo"` for `gemma-android`
- `"Analizado por Gemma en el servidor"` for `llm`
- `"Estructurado por reglas locales"` for `rules`

The chip is informational; it does not gate submission or escalation.

## 4. New environment variables introduced on this branch

| Name | Default | Purpose |
|---|---|---|
| `JALREKHA_FEWSHOT_COUNT` | `12` | Number of rioplatense few-shot examples injected into the structuring prompt. Drop to `4` for CPU-only dev to keep prompt processing under ~90 s. |
| `JALREKHA_ASR_ENABLED` | `true` | Master switch for the Whisper transcription path. Set to `false` to skip ASR entirely (typed transcripts only). |
| `JALREKHA_ASR_MODEL_SIZE` | `"tiny"` | Faster-Whisper model size. `tiny` is int8-quantized, ~75 MB cache, ~3× realtime on CPU. |
| `JALREKHA_ASR_MODEL_CACHE_DIR` | `backend/data/whisper-models` | Local cache directory for the downloaded Whisper weights. |
| `JALREKHA_VOLUNTEER_IMAGE_ENABLED` | inherits `JALREKHA_MULTIMODAL_ENABLED` | Separate flag so volunteer-photo assessment can be enabled while node-side multimodal stays off (or vice versa). |
| `JALREKHA_IMAGE_MAX_TOKENS` | `256` | Output token cap for the multimodal image assessor. On CPU-only dev hardware ~75% of latency is vision-encoder prompt processing (768x768 patches); dropping output tokens helps but is not the bottleneck. Use together with `JALREKHA_IMAGE_TIMEOUT_SECONDS`. |
| `JALREKHA_IMAGE_TIMEOUT_SECONDS` | `300` | HTTP timeout for `image_assessor.assess`. Decoupled from `JALREKHA_LLM_TIMEOUT_SECONDS` so a slow multimodal call does not force the structuring/reasoning pipeline to wait that long. On CPU-only dev with `IMAGE_MAX_TOKENS=120` the assess completes in ~190–220 s, so 300 s gives margin. |
| `JALREKHA_ACTUATORS_ENABLED` | `true` | When `false`, `dispatch_actuators` is short-circuited and no tool calls are issued regardless of alert level. In production with `JALREKHA_NODE_PROVIDER=litert`, actuator selection runs through `LiteRTNodeRuntime`; Ollama remains the explicit development provider when `JALREKHA_NODE_PROVIDER=ollama`. |

## 5. Latency on CPU-only development hardware

Measured during the JalRekha Volunteer integration branch on CPU-only hardware:

- Gemma 4 E2B: ~3.5 tokens/s sustained.
- ASR (Whisper tiny int8): first-call cold load ~35 s; transcription of a 30 s wav: ~5–10 s.
- Image assessment on a single frame (multimodal Gemma): ~190 s wall-clock (192 s for the USGS demo frame). This is the reason image assessment is wired as a FastAPI `BackgroundTask` and not synchronous inside the POST handler — a synchronous call would push the response well past any reasonable mobile HTTP timeout.
- Full `POST /api/reports` without image, with 4 few-shot examples: ~3 minutes.

Demo machines with GPU acceleration (the production target via MediaPipe on Android, or a Raspberry Pi paired with a hardware accelerator) bring these numbers into seconds. The CPU-only figures above are the floor, not the target.

## 6. Known gaps and out-of-scope items

- Native photo and audio capture inside the Android UI is NOT implemented in this PR. The device-capture path requires CameraX plus `MediaRecorder` wiring and was deferred because no physical device or emulator was available in this session. The PWA covers the demo path; Android currently exercises the on-device structuring layer against typed transcripts.
- The `.litertlm` asset (`gemma-4-E2B-it.litertlm` for LiteRT-LM, ~1.4 GB) is NOT bundled in the APK and is NOT auto-downloaded. The `GemmaOnDevice` wrapper expects it at `context.filesDir/gemma-4-E2B-it.litertlm`; the dev or operator places it there manually (see [`docs/android_gemma.md`](android_gemma.md) "Build & run" for the adb-push flow). MediaPipe `.task` was the original plan but Google has not shipped a Gemma 4 `.task` file, so the Android tier moved to LiteRT-LM — same artifact the backend uses.
- Android unit tests under `app/src/test/` are written but require an Android
  SDK. Run `./gradlew :app:testDebugUnitTest` in an Android-capable checkout.
- Real-device benchmarks for on-device Gemma latency are pending. The numbers in `docs/android_gemma.md` are still projections.
- iOS Safari `MediaRecorder` has well-known quirks; the PWA targets Chrome-class browsers.
- Production actuator dispatch no longer depends on Ollama when `JALREKHA_NODE_PROVIDER=litert`. The current LiteRT path uses strict JSON structured tool selection (`tool_calls`) through `LiteRTNodeRuntime`, not native LiteRT function calling. Unknown tools or malformed JSON make `dispatch_actuators` return `[]`; in the integrated `decision_engine` path, model-selected tools are constrained to deterministic recommended pending actuators for the alert level, and orange/red alerts then use deterministic fallback for any missing recommended actuators. The fallback can be total or partial without refiring tools already selected by LiteRT.
- Raspberry Pi 5 8GB smoke with real `LiteRTNodeRuntime` did not confirm parseable actuator JSON yet: two direct `dispatch_actuators`/selection runs with E2B text GPU were killed by external timeouts at 420 s and 300 s before emitting a normal response. This is a LiteRT structured-selection latency limitation to keep visible; it does not block orange/red actuation continuity because the decision engine records and fires missing deterministic recommended actuators when model selection is empty or incomplete.
- `frontend/src/pages/Calibration.tsx` has a pre-existing lint error (`react-hooks/immutability`: `draw` referenced before declaration). This bug is from commit `ce62b88` (P5 calibration UI, pre-JalRekha Volunteer branch). It is not introduced by this PR and is left for a separate fix so the diff stays focused on JalRekha Volunteer.

## 7. How to reproduce the demo flow

1. From the repo root: `./scripts/dev.sh` (starts Ollama, backend, and the PWA frontend; this is the existing entry point — no new launcher).
2. With Ollama warm, smoke-test the endpoint directly:

   ```bash
   curl -X POST http://127.0.0.1:8000/api/reports \
     -F "transcript_text=Hay agua sobre la calle y sigue subiendo" \
     -F "reporter_name=Demo" \
     -F "reporter_role=volunteer" \
     -F "offline_created=false" \
     -F "photo=@fixtures/frames/silverado_060s.jpg" \
     -F "audio=@/path/to/any_30s.wav"
   ```

   Any 30 s wav works for `audio`; the photo path above is the USGS demo frame already in the repo.
3. Open `http://127.0.0.1:5173`, navigate to Report, record voice, attach a photo, and submit through the PWA.
4. Observe: backend log shows `local alarm triggered ...`, the response carries alert level red, and `decision_trace` contains both `actuated: trigger_alarm, notify_app` (or similar, depending on what Gemma chose) AND eventually `image_description: ...` once the background task finishes.

## 8. References

- `docs/legacy/architecture.md` — shared backend architecture across JalRekha Node and JalRekha Volunteer.
- `docs/legacy/rioplatense_eval.md` — the few-shot corpus and structuring benchmark.
- `docs/android_gemma.md` — the on-device path (this PR wires it; that doc still carries projected, not measured, latencies).
