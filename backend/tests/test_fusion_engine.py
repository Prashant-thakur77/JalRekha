from __future__ import annotations

from datetime import datetime, timedelta

from jalrekha.fusion.engine import Signal, fuse


NOW = datetime(2026, 5, 16, 12, 0, 0)


def test_fusion_no_evidence():
    decision = fuse([], [])
    assert decision.severity == "none"
    assert decision.trigger_source == "none"


def test_fusion_node_only_caps_at_moderate():
    decision = fuse([Signal("n1", NOW, -34.6, -58.38, 0.95, "severe", "critico")], [])
    assert decision.severity == "moderate"
    assert decision.trigger_source == "node"


def test_fusion_citizen_only_info_needs_validation():
    decision = fuse([], [Signal("r1", NOW, -34.6, -58.38, 0.9, "severe", "ruta cortada")])
    assert decision.severity == "info"
    assert decision.needs_validation


def test_fusion_cross_source_can_escalate_severe():
    node = Signal("n1", NOW, -34.6, -58.38, 0.75, "moderate", "sube")
    report = Signal("r1", NOW + timedelta(minutes=3), -34.6005, -58.3805, 0.82, "severe", "casas afectadas")
    decision = fuse([node], [report])
    assert decision.severity == "severe"
    assert decision.trigger_source == "fused"
    assert not decision.needs_validation
