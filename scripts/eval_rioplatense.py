#!/usr/bin/env python3
"""P4 — rioplatense corpus benchmark.

Runs the held-out test split (split='test') through each adapter and reports
per-field accuracy. Paths:

  - rules: backend/.../services/report_structuring._fallback_parse
  - fewshot: GemmaFewShotTextStructurer (requires local Ollama + gemma4:e2b)
  - openai: optional reference (requires OPENAI_API_KEY, single run)

Usage:
    PYTHONPATH=backend/src python3 scripts/eval_rioplatense.py [rules|fewshot|openai|all]
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "datasets" / "rioplatense_hydro" / "corpus.jsonl"

sys.path.insert(0, str(ROOT / "backend" / "src"))

from jalrekha.services.report_structuring import _fallback_parse  # noqa: E402
from jalrekha.adapters.llm import OpenAICompatibleLLM  # noqa: E402
from jalrekha.adapters.text_structuring_gemma_fewshot import GemmaFewShotTextStructurer  # noqa: E402

FIELDS = ("water_level_category", "trend", "road_status", "bridge_status", "urgency")


def load_split(split: str) -> list[dict]:
    rows: list[dict] = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["split"] == split:
            rows.append(row)
    return rows


def run_rules(transcript: str) -> dict:
    r = _fallback_parse(transcript)
    return {
        "water_level_category": r.water_level_category,
        "trend": r.trend,
        "road_status": r.road_status,
        "bridge_status": r.bridge_status,
        "urgency": r.urgency,
    }


def run_fewshot(transcript: str, fewshot: GemmaFewShotTextStructurer) -> dict | None:
    out = fewshot.structure_observation(transcript, {"site_name": "demo", "region": "demo"})
    if not out:
        return None
    return {f: out.get(f, "unknown") for f in FIELDS}


def score(predictions: list[dict | None], gold: list[dict]) -> dict[str, float]:
    totals: dict[str, int] = defaultdict(int)
    hits: dict[str, int] = defaultdict(int)
    for pred, g in zip(predictions, gold):
        for field in FIELDS:
            totals[field] += 1
            if pred is not None and pred.get(field) == g.get(field):
                hits[field] += 1
    return {f: hits[f] / totals[f] if totals[f] else 0.0 for f in FIELDS}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    test = load_split("test")
    gold = [r["structured_output"] for r in test]
    transcripts = [r["transcript_es"] for r in test]
    print(f"# Rioplatense eval ({len(test)} test examples)\n")

    if mode in {"rules", "all"}:
        preds = [run_rules(t) for t in transcripts]
        acc = score(preds, gold)
        print("## rules")
        for f, v in acc.items():
            print(f"  {f}: {v:.2%}")
        print(f"  mean: {sum(acc.values()) / len(acc):.2%}\n")

    if mode in {"fewshot", "all"}:
        llm = OpenAICompatibleLLM()
        health = llm.health()
        if not health.reachable:
            print(f"## fewshot — SKIPPED (LLM unreachable: {health.detail})\n")
        else:
            fewshot = GemmaFewShotTextStructurer(llm)
            preds = [run_fewshot(t, fewshot) for t in transcripts]
            covered = sum(1 for p in preds if p is not None)
            acc = score(preds, gold)
            print(f"## fewshot ({health.model}) — coverage {covered}/{len(preds)}")
            for f, v in acc.items():
                print(f"  {f}: {v:.2%}")
            print(f"  mean: {sum(acc.values()) / len(acc):.2%}\n")

    if mode == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            print("## openai — SKIPPED (no OPENAI_API_KEY)")
            return 0
        print("## openai — run manually, see docs/legacy/rioplatense_eval.md for the documented prompt")

    return 0


if __name__ == "__main__":
    sys.exit(main())
