"""Thresholds and the autonomy policy. One place, so the report and the code agree.

Thresholds were set on synthetic training scenes and the training split of
the hydrograph events, then frozen (eval/config.frozen.json records the hash
of this file).
"""

from __future__ import annotations

# Rise rate (m/h, Kalman-filtered) that counts as a fast rise (D4).
R_FAST_M_PER_H = 0.30
# Below this for FALLING_CYCLES consecutive cycles after a peak -> falling (D9).
R_FALL_M_PER_H = -0.05
FALLING_CYCLES = 3
# A rise counts only when it is significant: rate - Z * rate_sigma >= R_FAST (D4, projected D5).
# Z chosen on the TRAIN split of the real gauge-pair evaluation (eval/config.leadtime.v2.frozen.json):
# smallest Z keeping camera-noise false alerts <= 1 per 30 days with <= 5 points detection loss.
RATE_SIGNIFICANCE_Z = 1.5
# Right after bad-quality frames, readings around the gap are suspect (a degradation can bias
# readings before the gate trips). A projected crossing then needs this many consecutive
# significant-rise cycles before D5 drafts anything. Gauge data has no gaps, so the
# lead-time evaluation is unaffected.
POST_GAP_CYCLES = 3
POST_GAP_RISE_STREAK = 3
# Snapshot cameras (one frame per cycle, so the temporal estimator E2 cannot run): three
# consecutive readings within this band, inside SNAPSHOT_WINDOW_H, count as the second vote.
SNAPSHOT_AGREE_M = 0.10
SNAPSHOT_WINDOW_H = 3.0
# Horizon for "projected to cross the warning level soon" (D5), hours.
CROSS_HORIZON_H = 1.5
# Reading uncertainty above which a second opinion is requested (D3), metres.
SIGMA_MAX_M = 0.08
# VLM vs CV disagreement that is treated as a contradiction (D7), metres.
VLM_CONTRADICTION_M = 0.30
# VLM vs CV agreement band that counts as confirmation, metres.
VLM_CONFIRM_M = 0.15
# The autonomous local siren (D6) also needs 2 of 3 estimators within 10 cm and sigma <= SIGMA_MAX_M.
SIREN_MIN_CONFIDENCE = 0.5
# Bad-quality frames in a row before asking a person for a photo (D1).
PHOTO_REQUEST_STREAK = 2
# Burst length normally and after a bad-quality frame (D1), frames.
BURST_NORMAL = 5
BURST_BOOST = 9
# Kalman history window.
HISTORY_HOURS = 6.0

# action -> (who may do it, approval needed)
AUTONOMY = [
    {"action": "measure_stage / request_burst / set_capture_cadence / register_heavy", "agent_alone": True, "human": "no", "why": "Changes only what the camera looks at; cheap and reversible"},
    {"action": "verify_with_vlm (Bedrock)", "agent_alone": True, "human": "no", "why": "Called only when estimators disagree or before a danger-level action; cost is traced"},
    {"action": "downstream_eta / draft_alert / draft CAP / synthesize voice", "agent_alone": True, "human": "no", "why": "Drafts are not sent; every number comes from a tool output"},
    {"action": "trigger_siren (local, at the camera site)", "agent_alone": True, "human": "acknowledge afterwards", "why": "Only when stage >= danger level, quality gate OK, 2 of 3 estimators agree within 10 cm and sigma <= 8 cm; guard rate-limits it (6/h per zone)"},
    {"action": "send_sms / voice_call / publish_cap (public)", "agent_alone": False, "human": "approval by the region's authority role", "why": "Public messages carry official weight"},
    {"action": "cross_border_notify", "agent_alone": False, "human": "approval by the downstream authority (DDMA / municipal EOC)", "why": "Crosses a jurisdiction; the receiving authority decides"},
    {"action": "all_clear", "agent_alone": False, "human": "approval", "why": "A false all-clear is the most dangerous error"},
    {"action": "publish_route_status / dispatch_relief", "agent_alone": False, "human": "approval", "why": "Sends people and boats"},
    {"action": "recalibrate (registration failed)", "agent_alone": False, "human": "field visit", "why": "Auto-actions at the site are suspended until a person re-calibrates"},
]

BRANCHES = {
    "D1": "Quality gate failed (night, blur, glare, fog): no alert from this frame; longer burst; photo request after repeats",
    "D2": "Registration: ORB failed -> ALIKED+LightGlue rescue; if both fail, site degraded and recalibration requested",
    "D3": "Estimators disagree or sigma too high -> second opinion from the VLM (expensive model only when needed)",
    "D4": "Fast rise -> capture cadence up, downstream ETA computed",
    "D5": "Warning level reached or projected within the horizon -> local and downstream (cross-border) alerts drafted for approval",
    "D6": "Danger level with good quality and agreeing estimators -> local siren (autonomous) + danger SMS drafted",
    "D7": "VLM contradicts a confident CV reading or returns malformed/injected text -> keep CV, flag for human review",
    "D8": "Relief photo says the road is blocked -> route-board update drafted for approval",
    "D9": "Falling after a peak -> cadence down, all-clear proposed for approval",
}
