from __future__ import annotations

import json
from pathlib import Path

from jalrekha.adapters.text_structuring_gemma_fewshot import (
    GemmaFewShotTextStructurer,
    _build_user_prompt,
    FEW_SHOT,
)
from jalrekha.services.report_structuring import _normalize_llm_payload


CORPUS = Path(__file__).resolve().parents[2] / "datasets" / "rioplatense_hydro" / "corpus.jsonl"


def test_corpus_has_required_size_and_splits():
    rows = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) >= 80
    splits = {r["split"] for r in rows}
    assert splits == {"train", "validation", "test"}


def test_few_shot_prompt_contains_all_examples():
    prompt = _build_user_prompt("test", {"site_name": "x"})
    for ex in FEW_SHOT:
        assert ex["in"] in prompt


def test_few_shot_parser_handles_llm_none():
    class FakeLLM:
        def generate_text(self, *a, **k):
            return None
    parser = GemmaFewShotTextStructurer(FakeLLM())
    assert parser.structure_observation("paso la marca", {"site_name": "x"}) is None


def test_few_shot_parser_extracts_json():
    class FakeLLM:
        def generate_text(self, *a, **k):
            return 'prefix {"water_level_category":"critical","trend":"rising","road_status":"blocked","bridge_status":"unknown","homes_affected":true,"urgency":"critical","summary":"x","confidence":0.9} tail'
    parser = GemmaFewShotTextStructurer(FakeLLM())
    out = parser.structure_observation("paso la marca", {"site_name": "x"})
    assert out is not None
    assert out["water_level_category"] == "critical"
    normalized = _normalize_llm_payload(out)
    assert normalized is not None
    assert normalized.urgency == "critical"


ADVERSARIAL_PHRASES = [
    ("ya tapo la calle y hay gente subida a los techos", "critical", "blocked", True),
    ("crece desde anoche, llega por las rodillas", "high", "caution", False),
    ("el puente esta tapado, agua arriba", "critical", "blocked", False),
    ("no podemos salir de casa, entro agua", "high", "blocked", True),
    ("paso la marca critica, cortamos la ruta", "critical", "blocked", False),
]


def test_adversarial_phrases_via_fewshot_wiring():
    """Given a well-behaved Gemma, the few-shot adapter + normalization path
    produces the expected structured output for each adversarial phrase.
    This validates wiring; live Gemma accuracy is measured by scripts/eval_rioplatense.py.
    """
    for phrase, water, road, homes in ADVERSARIAL_PHRASES:
        class FakeLLM:
            def __init__(self, w, r, h):
                self._payload = {
                    "water_level_category": w,
                    "trend": "rising",
                    "road_status": r,
                    "bridge_status": "unknown",
                    "homes_affected": h,
                    "urgency": "critical" if w == "critical" else "high",
                    "summary": "x",
                    "confidence": 0.9,
                }
            def generate_text(self, *a, **k):
                return json.dumps(self._payload)

        parser = GemmaFewShotTextStructurer(FakeLLM(water, road, homes))
        out = parser.structure_observation(phrase, {"site_name": "x"})
        assert out is not None, phrase
        normalized = _normalize_llm_payload(out)
        assert normalized is not None, phrase
        assert normalized.water_level_category == water, phrase
        assert normalized.road_status == road, phrase
        assert normalized.homes_affected == homes, phrase
