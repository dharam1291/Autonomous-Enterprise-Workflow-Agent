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
    entity_slots = ", ".join(f'"{n}": "<string or null>"' for n in entity_names)
    confidence_slots = ", ".join(f'"{n}": <float 0.0-1.0>' for n in entity_names)
    evidence_slots = ", ".join(f'"{n}": "<exact quote from document or null>"' for n in entity_names)
    return (
        "Extract the requested insurance claim entities from the document below.\n\n"
        "Return a single JSON object matching this EXACT structure — no extra keys, "
        "no deviations. Every value in 'entities' MUST be a string (even numbers like "
        '"4500" must be the string "4500") or null if not found.\n\n'
        "Required JSON schema:\n"
        "{\n"
        f'  "entities": {{{entity_slots}}},\n'
        f'  "confidence": {{{confidence_slots}}},\n'
        f'  "evidence": {{{evidence_slots}}},\n'
        '  "conflicts": {} // empty object, or {"<entity>": ["val1","val2"]} when '
        "the document contains contradictory values\n"
        "}\n\n"
        "Rules:\n"
        "- 'entities': extracted value as a STRING or null. Numbers must be strings.\n"
        "- 'confidence': per-entity float between 0.0 and 1.0.\n"
        "- 'evidence': the exact substring from the document that supports each value.\n"
        "- 'conflicts': only populated when multiple contradictory values are found.\n\n"
        f"Document:\n{text}"
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
