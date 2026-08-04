from __future__ import annotations

from app.domain.models import HumanReviewAction, WorkflowState


class LetterGenerator:
    def approval_letter(self, state: WorkflowState, human_approved: bool = False) -> str:
        claimant = state.extracted_entities.get_value("claimant_name") or "Claimant"
        amount = state.extracted_entities.get_value("claim_amount") or "the submitted amount"
        policy = state.extracted_entities.get_value("policy_number") or "the referenced policy"
        qualifier = "following caseworker review" if human_approved else "following automated validation"
        return (
            f"Dear {claimant},\n\n"
            f"We are pleased to inform you that your claim for {amount} under policy {policy} "
            f"has been approved {qualifier}. This draft is prepared for caseworker sign-off "
            "and final dispatch.\n\n"
            "Sincerely,\nClaims Operations Team"
        )

    def rejection_letter(self, state: WorkflowState, human_rejected: bool = False) -> str:
        claimant = state.extracted_entities.get_value("claimant_name") or "Claimant"
        policy = state.extracted_entities.get_value("policy_number") or "the referenced policy"
        reasons = [
            finding.message
            for finding in state.validation_findings
            if finding.outcome == "FAILED" and finding.layer != "HITL"
        ]
        reason_text = "; ".join(reasons[:3]) or "the claim did not satisfy required validation checks"
        qualifier = "after caseworker review" if human_rejected else "after validation"
        return (
            f"Dear {claimant},\n\n"
            f"Your claim under policy {policy} cannot be approved {qualifier}. "
            f"Reason: {reason_text}. This draft is prepared for caseworker review before final dispatch.\n\n"
            "Sincerely,\nClaims Operations Team"
        )

    def exception_summary(self, state: WorkflowState) -> str:
        claimant = state.extracted_entities.get_value("claimant_name") or "Unavailable"
        policy = state.extracted_entities.get_value("policy_number") or "Unavailable"
        amount = state.extracted_entities.get_value("claim_amount") or "Unavailable"
        failed_findings = [
            finding for finding in state.validation_findings if finding.outcome == "FAILED"
        ]
        reasons = "\n".join(f"- {finding.rule_id}: {finding.message}" for finding in failed_findings)
        return (
            "Exception Review Summary\n\n"
            f"Workflow ID: {state.workflow_id}\n"
            f"Claimant: {claimant}\n"
            f"Policy Number: {policy}\n"
            f"Claim Amount: {amount}\n\n"
            "Manual Review Reasons:\n"
            f"{reasons or '- Manual review requested by workflow policy.'}\n\n"
            "Recommended Action: Caseworker should verify supporting documentation and select "
            "Approve, Reject, or Request More Info."
        )

    def more_info_letter(self, state: WorkflowState) -> str:
        claimant = state.extracted_entities.get_value("claimant_name") or "Claimant"
        return (
            f"Dear {claimant},\n\n"
            "Additional information is required before your claim can be processed. "
            "A caseworker will contact you with the specific documentation required.\n\n"
            "Sincerely,\nClaims Operations Team"
        )

