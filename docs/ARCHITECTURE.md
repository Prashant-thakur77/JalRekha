# Architecture

## System

```mermaid
flowchart TB
  subgraph Field["Field: Nepal and India"]
    CAM["Staff-gauge camera"]
    VOL["Volunteer PWA / Android"]
    OPS["Operators: ward focal person (NP), DDMA control room (IN)"]
    SIREN["Local siren (edge rule)"]
  end
  APIGW["API Gateway HTTPS + throttling"]
  subgraph EC2["EC2 c8g.xlarge Graviton4 (COOL AMI wired)"]
    API["FastAPI + PWA"]
    CV["OpenCV 5 pipeline: quality, ORB / ALIKED+LightGlue, E1/E2/E3, Kalman, DIS, YuNet"]
    AG["Agent loop: policy D1-D9, guard, traces"]
    RG["Region profiles + river graphs"]
    DB[("SQLite: traces, approvals, relief")]
  end
  subgraph AWS["Managed AWS services"]
    BR["Bedrock (VLM 2nd opinion)"]
    PO["Polly (voice)"]
    SNS["SNS (operators, SMS)"]
    SFN["Step Functions (escalation timer)"]
    S3[("S3 (CAP, results)")]
    CW["CloudWatch + keep-warm Lambda"]
  end
  CAM -->|"burst + camera key"| APIGW
  VOL --> APIGW
  OPS <-->|"approve with PIN"| APIGW
  APIGW --> API --> CV --> AG
  AG <--> RG
  AG <--> DB
  AG -->|"only if estimators disagree"| BR
  AG --> PO
  AG -->|"approved messages"| SNS
  AG -->|"new public draft"| SFN
  SFN -->|"still pending"| SNS
  AG --> S3
  API --> CW
  AG -.->|"danger + good quality"| SIREN
```

## Agent workflow

```mermaid
flowchart TD
  F["Burst of frames"] --> M["measure_stage (OpenCV 5)"]
  M --> R{"Registered?"}
  R -- "ORB fails" --> H["ALIKED+LightGlue / keyframe chain"]
  H --> R2{"Gauge in view?"}
  R2 -- no --> DEG["D2: site degraded<br/>recalibration request (human)"]
  R2 -- yes --> Q
  R -- yes --> Q{"Quality gate OK?"}
  Q -- no --> D1["D1: no alert from this frame<br/>burst 5→9, photo request"]
  Q -- yes --> C{"2 of 3 estimators agree,<br/>sigma ≤ 8 cm?"}
  C -- no --> V["D3: VLM second opinion (Bedrock)"]
  V -- "unavailable" --> HOLD["hold reading, ask for photo"]
  V -- "contradicts / injected text" --> D7["D7: keep CV value, human review"]
  V -- confirms --> K
  C -- yes --> K["Kalman: level + rise rate"]
  D7 --> K
  K --> FAST{"significant rise?<br/>rate − 1.5σ ≥ 0.30 m/h"}
  FAST -- yes --> D4["D4: cadence 600→300 s<br/>downstream ETA bands"]
  K --> W{"≥ warning or projected<br/>crossing ≤ 1.5 h?"}
  D4 --> W
  W -- yes --> D5["D5: draft local + cross-border<br/>SMS · voice · CAP"]
  D5 --> APPR["Approval inbox (PIN, named approver)"]
  K --> DG{"≥ danger, quality OK,<br/>estimators agree?"}
  DG -- yes --> G["Guard: schema · severity ≤ evidence ·<br/>region bounds · 6/h rate limit"]
  G --> D6["D6: local siren (autonomous)"]
  K --> FALL{"falling 3 cycles<br/>after a peak?"}
  FALL -- yes --> D9["D9: cadence down,<br/>all-clear proposal → approval"]
  APPR --> DISP["Dispatch: SNS SMS · voice files · CAP to S3"]
```

Every box writes a step to the trace (`GET /api/agent/traces/{id}`); `docs/traces/README.md` lists the cycles where an OpenCV output changed the next action.
