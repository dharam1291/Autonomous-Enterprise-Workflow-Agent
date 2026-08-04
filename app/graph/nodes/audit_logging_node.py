from __future__ import annotations

from app.graph.state import ClaimGraphState
from app.services.rule_engine import RuleEngine


class AuditLoggingNode:
    def __init__(self, rule_engine: RuleEngine) -> None:
        self._rule_engine = rule_engine

    def __call__(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow = state["workflow"]
        workflow.current_step = "completed"
        workflow.add_findings(self._rule_engine.validate_final_decision(workflow))
        workflow.add_audit("Audit logging completed.")
        return state
