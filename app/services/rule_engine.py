from __future__ import annotations

import re
from decimal import Decimal

from app.domain.models import (
    EntityRequirement,
    ProviderConfig,
    RuleConfig,
    ValidationFinding,
    ValidationLayer,
    ValidationOutcome,
    ValidationSeverity,
    WorkflowState,
)


class RuleEngine:
    def validate_extraction(self, state: WorkflowState, config: ProviderConfig) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        for definition in config.entity_definitions:
            entity = state.extracted_entities.values.get(definition.name)
            missing = not entity or not entity.value
            low_confidence = bool(entity and entity.confidence < definition.confidence_threshold)

            if definition.requirement == EntityRequirement.MANDATORY and missing:
                findings.append(
                    ValidationFinding(
                        rule_id=f"MANDATORY_ENTITY_{definition.name.upper()}",
                        layer=ValidationLayer.EXTRACTION,
                        outcome=ValidationOutcome.FAILED,
                        severity=ValidationSeverity.BLOCKER,
                        message=f"Mandatory entity '{definition.name}' was not extracted.",
                    )
                )
            elif low_confidence:
                findings.append(
                    ValidationFinding(
                        rule_id=f"ENTITY_CONFIDENCE_{definition.name.upper()}",
                        layer=ValidationLayer.EXTRACTION,
                        outcome=ValidationOutcome.FAILED,
                        severity=ValidationSeverity.WARNING,
                        message=f"Entity '{definition.name}' is below confidence threshold.",
                        details={
                            "confidence": entity.confidence,
                            "threshold": definition.confidence_threshold,
                        },
                    )
                )
            else:
                findings.append(
                    ValidationFinding(
                        rule_id=f"ENTITY_{definition.name.upper()}",
                        layer=ValidationLayer.EXTRACTION,
                        outcome=ValidationOutcome.PASSED,
                        severity=ValidationSeverity.INFO,
                        message=f"Entity '{definition.name}' extraction check passed.",
                    )
                )

        for entity_name, candidates in state.extracted_entities.conflicts.items():
            findings.append(
                ValidationFinding(
                    rule_id=f"CONFLICTING_{entity_name.upper()}",
                    layer=ValidationLayer.EXTRACTION,
                    outcome=ValidationOutcome.FAILED,
                    severity=ValidationSeverity.ERROR,
                    message=f"Conflicting values found for '{entity_name}'.",
                    details={"candidates": candidates},
                )
            )

        return findings

    def validate_business(self, state: WorkflowState, config: ProviderConfig) -> list[ValidationFinding]:
        return [
            self._evaluate_rule(rule, state, ValidationLayer.BUSINESS)
            for rule in config.business_rules
            if rule.enabled
        ]

    def validate_hitl(self, state: WorkflowState, config: ProviderConfig) -> list[ValidationFinding]:
        return [
            self._evaluate_rule(rule, state, ValidationLayer.HITL)
            for rule in config.hitl_rules
            if rule.enabled
        ]

    def validate_final_decision(self, state: WorkflowState) -> list[ValidationFinding]:
        if state.status == "APPROVED" and state.has_blocking_failure():
            return [
                ValidationFinding(
                    rule_id="FINAL_APPROVAL_CONSISTENCY",
                    layer=ValidationLayer.FINAL_DECISION,
                    outcome=ValidationOutcome.FAILED,
                    severity=ValidationSeverity.BLOCKER,
                    message="Approved state is inconsistent with blocking validation failures.",
                )
            ]
        return [
            ValidationFinding(
                rule_id="FINAL_DECISION_CONSISTENCY",
                layer=ValidationLayer.FINAL_DECISION,
                outcome=ValidationOutcome.PASSED,
                severity=ValidationSeverity.INFO,
                message="Final decision consistency check passed.",
            )
        ]

    def _evaluate_rule(
        self,
        rule: RuleConfig,
        state: WorkflowState,
        layer: ValidationLayer,
    ) -> ValidationFinding:
        handlers = {
            "regex_match": self._regex_match,
            "decimal_lte": self._decimal_lte,
            "decimal_gt": self._decimal_gt,
            "feature_required": self._feature_required,
        }
        handler = handlers.get(rule.type)
        if not handler:
            return ValidationFinding(
                rule_id=rule.id,
                layer=layer,
                outcome=ValidationOutcome.SKIPPED,
                severity=ValidationSeverity.WARNING,
                message=f"Unsupported rule type '{rule.type}'.",
            )
        passed, details = handler(rule, state)
        return ValidationFinding(
            rule_id=rule.id,
            layer=layer,
            outcome=ValidationOutcome.PASSED if passed else ValidationOutcome.FAILED,
            severity=rule.severity,
            message=rule.description if passed else details.pop("failure_message", rule.description),
            details=details,
        )

    @staticmethod
    def _regex_match(rule: RuleConfig, state: WorkflowState) -> tuple[bool, dict]:
        entity_name = rule.parameters["entity"]
        pattern = rule.parameters["pattern"]
        value = state.extracted_entities.get_value(entity_name)
        passed = bool(value and re.fullmatch(pattern, value.strip()))
        return passed, {
            "entity": entity_name,
            "value": value,
            "pattern": pattern,
            "failure_message": f"Entity '{entity_name}' does not match the required format.",
        }

    @staticmethod
    def _decimal_lte(rule: RuleConfig, state: WorkflowState) -> tuple[bool, dict]:
        entity_name = rule.parameters["entity"]
        max_value = Decimal(str(rule.parameters["max"]))
        value = state.extracted_entities.get_decimal(entity_name)
        passed = value is not None and value <= max_value
        return passed, {
            "entity": entity_name,
            "value": str(value) if value is not None else None,
            "max": str(max_value),
            "failure_message": f"Entity '{entity_name}' exceeds maximum allowed value {max_value}.",
        }

    @staticmethod
    def _decimal_gt(rule: RuleConfig, state: WorkflowState) -> tuple[bool, dict]:
        entity_name = rule.parameters["entity"]
        threshold = Decimal(str(rule.parameters["threshold"]))
        value = state.extracted_entities.get_decimal(entity_name)
        triggered = value is not None and value > threshold
        return not triggered, {
            "entity": entity_name,
            "value": str(value) if value is not None else None,
            "threshold": str(threshold),
            "failure_message": f"Entity '{entity_name}' requires review because it is above {threshold}.",
        }

    @staticmethod
    def _feature_required(rule: RuleConfig, state: WorkflowState) -> tuple[bool, dict]:
        feature_name = rule.parameters["feature"]
        enabled = bool(rule.parameters.get("enabled", True))
        return enabled, {
            "feature": feature_name,
            "enabled": enabled,
            "failure_message": f"Feature '{feature_name}' is disabled.",
        }

