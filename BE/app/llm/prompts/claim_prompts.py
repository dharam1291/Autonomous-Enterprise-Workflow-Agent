"""Shared prompt templates for insurance claim LLM operations.

Centralizes the system prompts and user-prompt builders so every provider
client (OpenAI, Anthropic, ...) issues identical instructions.
"""

from __future__ import annotations

from app.domain.models import ProviderConfig, WorkflowState

# System prompts shared by all providers.
JSON_SYSTEM_PROMPT = "You extract and validate insurance claim data. Return JSON only."
LETTER_SYSTEM_PROMPT = "You draft clear, compliant insurance claim correspondence."


def classification_prompt(text: str, config: ProviderConfig) -> str:
    return (
        "Classify whether this is a supported insurance claim document. "
        "Return JSON with keys is_claim, reason, and matched_signals.\n\n"
        f"Signals: {config.document_signals}\n\nDocument:\n{text}"
    )


def entity_extraction_prompt(text: str, config: ProviderConfig) -> str:
    entity_names = [definition.name for definition in config.entity_definitions]
    return (
        "Extract the requested insurance claim entities. Return strict JSON with keys "
        "entities, confidence, evidence, and conflicts. Use null for missing values.\n\n"
        f"Entities: {entity_names}\n\nDocument:\n{text}"
    )


def letter_prompt(state: WorkflowState, letter_type: str) -> str:
    return (
        f"Draft a concise professional claim {letter_type} letter from this workflow state:\n"
        f"{state.model_dump_json()}"
    )


def exception_summary_prompt(state: WorkflowState) -> str:
    return (
        "Draft a concise manual review exception summary from this workflow state:\n"
        f"{state.model_dump_json()}"
    )
