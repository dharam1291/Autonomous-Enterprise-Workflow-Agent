from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkflowStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    WAITING_FOR_HUMAN_REVIEW = "WAITING_FOR_HUMAN_REVIEW"
    APPROVED_BY_HUMAN = "APPROVED_BY_HUMAN"
    REJECTED_BY_HUMAN = "REJECTED_BY_HUMAN"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
    INVALID_DOCUMENT = "INVALID_DOCUMENT"
    FAILED = "FAILED"


class ValidationLayer(StrEnum):
    GUARDRAIL = "GUARDRAIL"
    DOCUMENT = "DOCUMENT"
    EXTRACTION = "EXTRACTION"
    BUSINESS = "BUSINESS"
    HITL = "HITL"
    FINAL_DECISION = "FINAL_DECISION"


class ValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKER = "BLOCKER"


class ValidationOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class HumanReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_MORE_INFO = "request_more_info"


class EntityRequirement(StrEnum):
    MANDATORY = "mandatory"
    OPTIONAL = "optional"


class EntityDefinition(BaseModel):
    name: str
    requirement: EntityRequirement
    patterns: list[str] = Field(default_factory=list)
    confidence_threshold: float = Field(default=0.75, ge=0, le=1)


class RuleConfig(BaseModel):
    id: str
    description: str
    type: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)


class HitlPolicy(BaseModel):
    review_timeout_minutes: int = Field(default=30, ge=1)
    on_timeout: Literal["escalate", "keep_pending"] = "escalate"
    escalation_role: str = "senior_caseworker"


class LLMConfig(BaseModel):
    provider: Literal["deterministic", "openai", "anthropic"] = "deterministic"
    model: str = "local-regex-extractor"
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=1200, ge=1)


class ProviderConfig(BaseModel):
    tenant_id: str = "default"
    provider_id: str = "default"
    display_name: str = "Default Provider"
    enabled: bool = True
    document_signals: list[str] = Field(default_factory=list)
    minimum_signal_match: int = 1
    entity_definitions: list[EntityDefinition]
    business_rules: list[RuleConfig] = Field(default_factory=list)
    hitl_rules: list[RuleConfig] = Field(default_factory=list)
    features: dict[str, bool] = Field(default_factory=dict)
    hitl_policy: HitlPolicy = Field(default_factory=HitlPolicy)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    letter_templates: dict[str, str] = Field(default_factory=dict)


class ExtractedEntity(BaseModel):
    name: str
    value: str | None
    confidence: float = Field(ge=0, le=1)
    evidence: str | None = None


class ClaimEntities(BaseModel):
    values: dict[str, ExtractedEntity] = Field(default_factory=dict)
    conflicts: dict[str, list[str]] = Field(default_factory=dict)

    def get_value(self, name: str) -> str | None:
        entity = self.values.get(name)
        return entity.value if entity else None

    def get_decimal(self, name: str) -> Decimal | None:
        raw_value = self.get_value(name)
        if not raw_value:
            return None
        normalized = raw_value.replace("$", "").replace(",", "").strip()
        try:
            return Decimal(normalized)
        except Exception:
            return None


class ValidationFinding(BaseModel):
    rule_id: str
    layer: ValidationLayer
    outcome: ValidationOutcome
    severity: ValidationSeverity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class HumanReviewTask(BaseModel):
    assigned_role: str = "caseworker"
    due_at: datetime
    status: Literal["PENDING", "COMPLETED"] = "PENDING"
    reviewer: str | None = None
    action: HumanReviewAction | None = None
    notes: str = ""
    completed_at: datetime | None = None


class WorkflowState(BaseModel):
    workflow_id: str = Field(default_factory=lambda: f"WF-{uuid4().hex[:12].upper()}")
    tenant_id: str
    provider_id: str
    source_name: str
    status: WorkflowStatus = WorkflowStatus.RECEIVED
    current_step: str = "received"
    document_text: str
    extracted_entities: ClaimEntities = Field(default_factory=ClaimEntities)
    validation_findings: list[ValidationFinding] = Field(default_factory=list)
    recommendation: str | None = None
    generated_letter: str | None = None
    exception_summary: str | None = None
    review_task: HumanReviewTask | None = None
    audit_events: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def add_audit(self, message: str) -> None:
        timestamp = datetime.now(UTC).isoformat()
        self.audit_events.append(f"{timestamp} | {message}")
        self.updated_at = datetime.now(UTC)

    def add_findings(self, findings: list[ValidationFinding]) -> None:
        self.validation_findings.extend(findings)
        self.updated_at = datetime.now(UTC)

    def has_blocking_failure(self) -> bool:
        return any(
            finding.outcome == ValidationOutcome.FAILED
            and finding.severity in {ValidationSeverity.ERROR, ValidationSeverity.BLOCKER}
            for finding in self.validation_findings
        )
