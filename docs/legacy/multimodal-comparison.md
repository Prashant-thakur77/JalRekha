# P2 - Gemma Temporal Assessment and Evidence Frames

`JalRekha Node` is now a **Gemma-first temporal assessment engine**. The evidence
frame overlay remains part of the demo, but it is no longer the core claim.
The core claim is that Gemma consumes a curated temporal bundle and emits the
node verdict.

## Current architecture

- OpenCV: sampling, ROI/band processing, overlays, waterline ratio hints, motion/contrast/edge hints.
- Gemma runner: receives the temporal evidence pack and returns:
  - `assessment_level`
  - `assessment_score`
  - `temporal_summary`
  - `reasoning_summary`
  - `reasoning_steps`
  - `critical_evidence`
- Image assessment overlay: optional supporting view rendered over the chosen
  evidence frame for operators and judges.

## Demo comparison

Using `fixtures/frames/silverado_060s.jpg` and two synthetic frames from the
test fixture:

### Frame/sequence A - Silverado reference sequence

| Source | Output |
|---|---|
| Temporal evidence builder | Curated highest-risk window + selected frame bundle + ratio/motion/edge hints |
| Gemma temporal runner | `assessment_level=red`, `assessment_score~0.8+`, temporal summary describing sustained rise and corroborating critical evidence |
| Evidence-frame overlay | Spanish one-line description of visible water and infrastructure risk |

### Frame/sequence B - synthetic rising waterline

| Source | Output |
|---|---|
| Temporal evidence builder | Rising lower band preserved across the curated sequence |
| Gemma temporal runner | Orange/red depending on runner availability and fallback |
| Evidence-frame overlay | Water visible, no meaningful infrastructure context |

### Frame/sequence C - synthetic calm baseline

| Source | Output |
|---|---|
| Temporal evidence builder | Low ratio hints, low escalation evidence |
| Gemma temporal runner | Green/yellow depending on the exact bundle and fallback path |
| Evidence-frame overlay | May be skipped or produce a conservative low-risk description |

## Honesty note

The demo still shows an evidence-frame caption because it is visually strong,
but the architectural novelty is no longer "Gemma narrates what OpenCV already
decided". The novelty is:

1. bounded temporal evidence curation on the edge
2. Gemma-first node assessment over that sequence
3. persistence of a rich audit pack for review and judging
