from __future__ import annotations

from app.graph.state import ClaimGraphState
from app.services.rule_engine import RuleEngine


class ExtractionQualityValidationNode:
    def __init__(self, rule_engine: RuleEngine) -> None:
        self._rule_engine = rule_engine

    def __call__(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow = state["workflow"]
        workflow.current_step = "extraction_quality_validation"
        workflow.add_findings(self._rule_engine.validate_extraction(workflow, state["provider_config"]))
        workflow.add_audit("Extraction quality validation completed.")
        return state
