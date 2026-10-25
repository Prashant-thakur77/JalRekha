# App builds

Place demo builds here before zipping the package:

- `volunteer-demo.apk` — Android JalRekha Volunteer build with `DEMO_MODE=true` (loads
  `inputs/audio/*` and `outputs/logs/volunteer_report_run.jsonl` instead of
  the live mic + radio channel).
- `jalrekha-dashboard-demo.zip` — static dashboard build (`pnpm build`
  output of `frontend/`) configured to read `outputs/alerts/*.json`.

Both builds are **optional**. The notebook live demo does not depend
on them. They exist so judges with an Android device or a local web server
can poke the real UIs.

## Build commands (for the team, not the judge)

```bash
# Android
cd android && ./gradlew :app:assembleDemoRelease
cp app/build/outputs/apk/demoRelease/app-demoRelease.apk \
   ../demo-artifacts/jalrekha-demo-artifacts/app/volunteer-demo.apk

# Dashboard
cd frontend && pnpm install && pnpm build
cd dist && zip -r ../../demo-artifacts/jalrekha-demo-artifacts/app/jalrekha-dashboard-demo.zip .
```
