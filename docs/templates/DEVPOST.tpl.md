# Devpost text: NadiSaathi

## Tagline

A camera reads the river in metres; an agent warns the next country downstream.

## Inspiration

On 29 September 2024 the Kosi at the Birpur barrage in Bihar peaked at 661,295 cusecs, the highest since 1968. In the same storm Nepal counted 209 dead. The water that floods Bihar comes from Nepal's hills, hours earlier, and Bihar's own forecast bulletins in October 2026 still noted that observed water-level data from Nepal were unavailable to them. We wanted the hours between "the river is rising at Chatara" and "the water is at Birpur" to reach the people in Birpur.

## What it does

A fixed camera looks at a staff gauge. OpenCV 5 turns each burst of frames into a river stage in metres with an error bar. An agent decides what to do next from that number: look more often, ask a bigger model for a second opinion only when its own estimators disagree, compute when the wave reaches each town downstream, and draft short alerts in Nepali, Hindi, Maithili, Bhojpuri and English, with a voice version and a CAP file. A ward focal person in Nepal or a DDMA operator in India approves with a PIN; nothing public goes out without them. After the flood, volunteers log relief needs by text or voice, and a road photo check estimates water depth against a reference object.

Live: https://gaq7chhmb2.execute-api.us-east-1.amazonaws.com (open Live, run the Koshi replay).

## Results (every number from a script in the repo)

- Real USGS staff-gauge cameras, physical calibration with nothing fitted: {{real_full_mae_cm}} cm mean error on {{real_n}} frames (median {{real_full_median_cm}} cm), against {{real_b0_mae_cm}} cm for the original method. On these hourly snapshots the colour estimator alone does as well as the fusion.
- The same agent on a real USGS camera through a July 2026 flood: {{rr_used_mae_cm}} cm error on the readings it used, siren on the first frame above danger, no alert drafts on quiet days. It gained no warning lead there: the rise came overnight, when that camera records nothing.
- Real river gauge pairs ({{lt_pairs}}, held-out 2024–2026): with official NWS action stages, our pre-registered primary, watching upstream gains a median {{lt_nws_gain_median_min}} min (mean {{lt_nws_gain_mean_h}} h). With percentile warning levels it gains a median {{lt_p95_gain_median_h}} h. We report both.
- Agent suite ({{ag_runs}} runs): alerts a median {{ag_lead_median_min}} min before the true warning crossing ({{rb_lead_median_min}} min for a threshold agent) with {{ag_false_alert_runs}} false alerts; the same projection rule without the vision gates raised {{pj_false_alert_runs}} false alerts when a knocked camera misread the river.
- Guard: {{guard_caught}}/{{guard_bad}} lying, injected (English/Hindi/Nepali) or malformed vision-model replies caught; {{guard_confirm_ok}} honest ones accepted.
- Graviton4 c8g vs x86 c7i, same 4 vCPU: {{B_fps}} vs {{C_fps}} frames/s, {{B_usd_1m}} vs {{C_usd_1m}} per million frames, identical outputs.

## How we built it

OpenCV 5: quality gate, ORB registration with ALIKED+LightGlue rescue through the new DNN engine, three waterline estimators (Sobel, DIS optical flow, Lab colour step), robust fusion, `cv2.KalmanFilter`, YuNet face and plate blur, GrabCut for flood photos. FastAPI and SQLModel on an EC2 c8g.xlarge (Graviton4) behind API Gateway, deployed by one CloudFormation stack; S3, Polly, SNS, Bedrock, CloudWatch, SSM, Budgets. React PWA in English, Hindi and Nepali.

## Challenges

Our first real-camera protocol fitted a line on each site's early frames and failed ({{real_fitted_protocol_mae_cm}} cm, no better than a constant). Clicking the printed gauge numerals once, as an installer would, brought it to {{real_full_mae_cm}} cm. In the replays, high water hides the features registration needs and ALIKED+LightGlue recovers it; on one real camera that was reframed after a flood, registration made accuracy worse, and we report that. Official warning levels are not consistent along a river, which erased most of the cross-river lead time in the primary evaluation. Bedrock quotas on a new account are zero, so the agent's fallback is what runs in the demo.

## What we learned

The cheap deterministic measurement should decide when to spend money on a large model, not the other way round. And an honest null result taught us more about cross-border warnings than a good number would have: the warning levels have to agree before the hours can be used.

## What's next

Real footage from a Koshi or Karnali gauge with a community early-warning programme; Nepali voice; DLT-registered SMS in India; running the COOL AMI comparison; conversations with DHM, CWC and DDMA control rooms. None of these partnerships exist yet.

## Testing instructions for judges

1. Open the live URL (it opens on Live). Keep "Koshi: rise to the peak" selected and press Run replay (about a minute).
2. Watch the overlay and the stage chart; open any trace to see which OpenCV number changed which action.
3. Approvals: the drafts from that replay stay open. Edit and approve the Hindi alert for Supaul with the PIN from the private testing field; the dispatch result (SMS simulated to verified test numbers only, voice files, CAP to S3) appears on the card. The full-night replay ("Koshi: the river rises...") continues past the peak and ends with an all-clear proposal, which supersedes the unapproved rise drafts.
4. Agent trace page: "Try to fool the guard". Type a lying or instruction-carrying model reply in any language and watch the agent keep the OpenCV value.
5. Rivers: compute ETAs from Chatara. Relief: submit a request in Hindi or Nepali, try a photo check.
6. Code, evaluation scripts and the report: the repository (`make test`, `make eval`, `make check-numbers`).
