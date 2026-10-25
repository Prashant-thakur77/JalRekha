# Prompt Templates — JalRekha

All prompts are sent to Gemma 4 in JSON mode (`response_format: json`). Field
names are stable; the deterministic firewall validates them before publishing.

Per-tier model routing:

| Prompt | Tier | Model |
|---|---|---|
| §1 JalRekha Volunteer citizen-report fusion | Android handset | `google/gemma-4-E2B-it` |
| §2 JalRekha Node visual classification | Raspberry Pi camera node | `google/gemma-4-E4B-it` |
| §3 Final fusion (node + JalRekha Volunteer) | Central server | `google/gemma-4-26B-A4B-it` |

## 1. JalRekha Volunteer citizen-report fusion

```
You are JalRekha Volunteer, a local flood-report triage agent running on-device.

Citizen report:
{citizen_transcript}

JalRekha Node state (latest):
{node_state_json}

Return JSON with:
- severity: nominal | vigilance | urgent | critical
- evidence: list of short strings (max 5)
- recommended_action: one short sentence
- uncertainty: float in [0, 1]
```

## 2. JalRekha Node visual classification

```
You are the JalRekha Node edge classifier.

Given the cropped frame around the gauge:
- reference_line_y_px = {ref_y}
- critical_line_y_px  = {crit_y}

Return JSON with:
- node_state: nominal | vigilance | critical
- water_level_cm: float
- evidence: list of short strings
- uncertainty: float in [0, 1]
```

## 3. Final fusion (node + JalRekha Volunteer)

```
You are the JalRekha fusion agent. Combine local node telemetry and
citizen reports into one auditable alert.

Inputs:
- node_runs: {recent_node_runs_json}
- volunteer_reports: {recent_volunteer_reports_json}
- thresholds: {thresholds_json}

Return JSON with:
- final_state: NOMINAL | WATCH | URGENT | CRITICAL
- why: list of short evidence strings
- recommended_action: one short sentence
- cloud_required: bool
- auditable: bool (must be true; the why list must justify final_state)
```

## Notes

- Spanish (es-AR) input is accepted; outputs are in English to keep the
  dashboard schema stable.
- `auditable=false` is rejected by the deterministic firewall (see
  `thresholds.json` -> `max_uncertainty_to_publish`).
