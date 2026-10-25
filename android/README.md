# Android MVP

Android app for the JalRekha MVP.

Current scope:
- dashboard with runtime, alerts and sites
- site detail with sample-node analysis and hydromet refresh
- volunteer report submission
- offline Room queue with manual flush and startup sync worker
- numeric calibration form
- configurable backend base URL for emulator or device

Default backend URL:
- emulator: `http://10.0.2.2:8000/api/`

To use on a real device, replace it from the Settings screen with your machine LAN URL, for example:
- `http://192.168.1.20:8000/api/`

Expected backend stack:
- `./scripts/dev.sh`
- or backend + Ollama + frontend started separately

## On-device Gemma model

The on-device parser (`GemmaOnDevice.kt`) loads `gemma-4-E2B-it.litertlm`
from the app's internal files dir at runtime. Without it, the app falls
back to sending the report to the backend.

Get the model:

```bash
# Downloads to backend/data/models/gemma-4-E2B-it.litertlm
python scripts/fetch_litert_model.py
```

Push it to the connected device (debug build, app installed at least once):

```bash
adb push backend/data/models/gemma-4-E2B-it.litertlm \
  /sdcard/Android/data/com.jalrekha.android/files/gemma-4-E2B-it.litertlm
```

Or, for a real `filesDir` placement, use `adb shell run-as
com.jalrekha.android` and copy into `files/` directly.

Verify with `adb logcat -s GemmaOnDevice`: on first report you should see
`raw response (audio=...)` followed by a JSON envelope. If you see the
report being submitted to the backend instead, the model file is not at
the expected path.

Android tooling note:
- The official Android tools page says the Android CLI is designed to work with agents and that projects can then be opened in Android Studio for visual tools and debugging.
- This module is structured to be opened directly in Android Studio under `android/`.
