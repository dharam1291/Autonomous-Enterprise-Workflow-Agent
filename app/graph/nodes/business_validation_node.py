from __future__ import annotations

from app.graph.state import ClaimGraphState
from app.services.rule_engine import RuleEngine


class BusinessValidationNode:
    def __init__(self, rule_engine: RuleEngine) -> None:
        self._rule_engine = rule_engine

    def __call__(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow = state["workflow"]
        workflow.current_step = "business_rule_validation"
        workflow.add_findings(self._rule_engine.validate_business(workflow, state["provider_config"]))
        workflow.add_audit("Business rule validation completed.")
        return state
