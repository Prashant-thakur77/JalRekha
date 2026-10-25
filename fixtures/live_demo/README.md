# JalRekha live demo fixtures

This folder contains the small fixture pack for the public hardware replay notebook
notebook. It is intentionally safe to publish and does not connect judges to a
live Raspberry Pi.

Contents:

- `manifest.json`: fixture inventory and required CSV columns.
- `sensor_readings.csv`: synthetic-safe JalRekha Node readings.
- `volunteer_reports.jsonl`: replay JalRekha Volunteer citizen reports.
- `frames/*.jpg`: synthetic-safe visual states for nominal, vigilance, urgent,
  and critical water levels.
- `transcripts/report_01.txt`: transcript used instead of audio for reliability.
- `expected_outputs/alert_trace.json`: golden fixture output used by default.

Default notebook mode is `RUN_GEMMA = False`, so the notebook demonstrates the
same data contract, same prompt contract, and same alert orchestration without
running live LiteRT-LM or Gemma inference. The real Raspberry Pi 5 + LiteRT-LM
evidence is documented separately in the repo docs, benchmark card, and demo
video artifacts.

The SINAGIR/CAP-shaped output in this fixture pack is a preview only. It is not
submitted to SINAGIR production endpoints.
