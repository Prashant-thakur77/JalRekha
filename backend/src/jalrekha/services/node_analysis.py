"""Compatibility module for older imports.

The fixed JalRekha Node no longer runs an OpenCV heuristic analyzer. Use
`services.node_assessment.MultimodalEvidenceBuilder` plus the Gemma 4
multimodal runner instead.
"""

from jalrekha.services.node_assessment import NodeAssessmentEngine, MultimodalEvidenceBuilder


__all__ = ["NodeAssessmentEngine", "MultimodalEvidenceBuilder"]
