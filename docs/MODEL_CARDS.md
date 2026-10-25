# Model cards

## JalRekha stage estimator (OpenCV 5 pipeline)

- Purpose: river stage in metres from a fixed camera that sees a staff gauge, with an uncertainty. Decision support for flood warning; not a replacement for official gauges.
- Inputs: a burst of 1–9 frames, a staff-gauge calibration (two or more clicked gauge marks with their values), a reference frame.
- Method: quality gate, ORB registration with ALIKED+LightGlue fallback, three estimators (Sobel edge energy, DIS-flow temporal texture, Lab colour step), weighted-median fusion, Kalman filter. Thresholds were set on synthetic training scenes (seeds 0–9) and frozen (`eval/config.frozen.json`).
- Evaluation: real USGS cameras, 2 sites, physical calibration, MAE about 10 cm on held-out frames; synthetic held-out scenes about 8 cm (see `README.md` for the generated numbers).
- Known failure modes: specular glare on the gauge; still water for the temporal estimator; a camera reframed after a flood (registration can make it worse); gauges whose datum differs from the official gauge; water outside the gauge's printed range (reported at the gauge end).
- Not for: discharge estimation (the surface-speed output is a proxy), people counting or any identification.

## YuNet face and licence-plate detectors (opencv_zoo)

- Use: blur faces and number plates before any frame is stored or shown. Runs on every stored frame.
- Weights: downloaded at runtime with SHA-1 checks (`backend/src/jalrekha/vision/models.py`), not redistributed. Face detector MIT, plate detector Apache-2.0 (per opencv_zoo).
- Limits: small or turned-away faces at long range can be missed; a miss means a face could remain in a stored frame. Mitigation: ROI-only storage mode is available.

## ALIKED + LightGlue (ONNX, through the OpenCV 5 DNN engine)

- Use: re-registration only when ORB fails (rain, high water hiding features, camera knock). About 1.2 s per call on Graviton4, so it is an escalation, not the default.
- Weights: ALIKED (BSD-3-Clause), LightGlue (Apache-2.0), downloaded at runtime with SHA-1 checks.

## Vision-language second opinion (Amazon Bedrock, Nova Lite by default)

- Use: only when fewer than two estimators agree, or before the first danger-level action. The reply must be one JSON object with `stage_m`, `confidence`, `visible`; anything else is reported and ignored. If it contradicts a confident OpenCV reading, the reading is kept and a person is asked.
- Status: wired, but unavailable on the deployment account (Nova token quota is zero). The fallback path is what runs.

## Relief photo check (GrabCut)

- Use: is a road or bridge flooded, and how deep at a reference object of known height. Output always carries `needs_review=true`.
- Assumption: a depth of 0.30 m or more makes a road unsafe; configurable. The user taps the top and the base of the reference object.
- Limits: water that looks like road (smooth asphalt in shadow), reflections, objects not vertical in the image. Tested on synthetic images only.

## Relief request parser (rules)

- Use: need (rescue, medical, water, food, shelter), number of people, urgency, from text in English, Hindi, Nepali, Maithili or Bhojpuri. Duplicates within 3 h and 500 m are merged.
- Limits: keyword rules; unusual phrasing falls back to "other". People counts in words ("twelve", "बारह") are not parsed. Households are converted at 5 people each and the response says so.

## Speech (voice reports and alert audio)

- Alert audio: Amazon Polly Kajal (neural) for Hindi and English; Polly has no Nepali, Maithili or Bhojpuri voice, so Nepali uses espeak-ng (offline) and Maithili/Bhojpuri use a labelled fallback voice.
- Voice reports: faster-whisper on the edge. The Whisper paper reports FLEURS word error rates of 21.5% for Hindi and 47.1% for Nepali (large-v2), so transcripts are always shown to a person with the audio.
