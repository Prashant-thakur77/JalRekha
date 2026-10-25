# P7 — On-device Gemma on Android

## Stack

Confirmed by P0 recon: Kotlin + Jetpack Compose, `compileSdk=34`, `minSdk=26`,
Retrofit for backend API, Room for offline queue. Gemma runtime is added via
**LiteRT-LM Android** (`com.google.ai.edge.litertlm:litertlm-android`) — the
native Android binding for the same `.litertlm` artifact the backend loads on
the Pi/workstation tier.

Alternatives considered:

- **MediaPipe LLM Inference** (`com.google.mediapipe:tasks-genai`) — was the
  original plan, but Google has not published a Gemma 4 `.task` file. The
  format only exists for Gemma 3 / 3n, so the `tasks-genai` path was unusable
  for the target model. Dropped.
- **llama.cpp via JNI** — works with `.gguf` but requires ABI-specific native
  builds and an extra conversion. Deferred.

## Files added

- `android/app/src/main/java/com/jalrekha/android/data/GemmaOnDevice.kt`
  — thin wrapper over LiteRT-LM `Engine` / `Conversation`. Single-source model
  path (`gemma-4-E2B-it.litertlm`) shared with the backend.
- `android/app/build.gradle.kts` — `com.google.ai.edge.litertlm:litertlm-android:0.11.0`
  declared as a real dependency (no reflective load: the runtime is required).

## Model choice

`gemma-4-E2B-it.litertlm` (int4, ~1.4 GB). E4B exceeds comfort on mid-range
Android (Snapdragon 7-gen), so E2B is the production target. E4B can be a
stretch profile for flagships; the same `GemmaOnDevice` code path works as
long as the artifact name and `MODEL_FILE_NAME` are updated.

The artifact is NOT bundled in the APK (keeps APK <50 MB). It is placed at
runtime — see "Build & run" below.

## Volunteer report flow

1. User fills transcript on `Report` screen.
2. `MainViewModel.submitReport` calls `gemma.structureReport(transcript)` if
   `gemma.isAvailable()`; otherwise shows an explicit error banner
   ("Modelo local no disponible, reintentá o usá sincronización con servidor")
   and requires the user to confirm backend sync.
3. On success, the parsed JSON goes into the local Room DB **labeled
   `parser_source = "gemma-android"`**.
4. UI displays a small chip: `Analizado con Gemma en este dispositivo` vs
   `Analizado en servidor` depending on `parser_source`.

## Latency budget

Target: **<12 s** combined text+image on mid-range device. Expected profile
(projections from public LiteRT-LM E2B benchmarks, not measurements on the APK
— see "Limitations" below):

| Phase | Mid-range (Snapdragon 7-gen, 8GB) | Flagship (SD 8-gen) |
|---|---|---|
| Cold load `.litertlm` → engine ready | 3.8 s | 1.9 s |
| Text structure (220 tokens, E2B) | 4.2 s | 1.6 s |
| Image assessment (frame, E2B) | 5.8 s | 2.3 s |

On emulator (no GPU) cold load can spike to ~18 s; document and fall back to
backend sync in that case.

## Build & run

1. Get the model with the repo's fetch script (same one the backend uses):

   ```bash
   python scripts/fetch_litert_model.py
   # writes backend/data/models/gemma-4-E2B-it.litertlm
   ```

2. Install the debug APK on the device:

   ```bash
   cd android
   ./gradlew :app:assembleDebug
   adb install app/build/outputs/apk/debug/app-debug.apk
   ```

3. Push the model into the app's internal files dir. Two options:

   ```bash
   # external storage path (debug build, accessible without run-as)
   adb push backend/data/models/gemma-4-E2B-it.litertlm \
     /sdcard/Android/data/com.jalrekha.android/files/gemma-4-E2B-it.litertlm

   # OR the real filesDir via run-as
   adb push backend/data/models/gemma-4-E2B-it.litertlm /data/local/tmp/
   adb shell run-as com.jalrekha.android cp \
     /data/local/tmp/gemma-4-E2B-it.litertlm files/
   ```

4. Verify with `adb logcat -s GemmaOnDevice`: the first report should print
   `LiteRT-LM engine ready in <N>ms (gemma-4-E2B-it.litertlm)` followed by a
   raw JSON envelope. If you see backend sync instead, the model file is not
   where `GemmaOnDevice` expects it (`context.filesDir/gemma-4-E2B-it.litertlm`).

## Limitations (honest)

- Physical Android-device validation is still pending; all latency numbers in
  this doc are projections from public LiteRT-LM benchmarks, not measurements
  on the APK.
- The runtime hard-depends on `litertlm-android` and fail-fasts at engine init
  if the artifact is missing or the device is too constrained — no silent
  backend fallback (deliberate design choice).
- Image multimodal path on LiteRT-LM Android is wired (`maxNumImages` /
  `Content.AudioBytes` in `GemmaOnDevice.kt`) but the volunteer flow currently
  exercises only the text+audio prompts. Image assessment from the Android
  client stays backend-only for the v1 pitch.
