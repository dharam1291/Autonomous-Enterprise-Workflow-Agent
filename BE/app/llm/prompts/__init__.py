"""Shared LLM prompt templates."""

from app.llm.prompts.claim_prompts import (
    JSON_SYSTEM_PROMPT,
    LETTER_SYSTEM_PROMPT,
    classification_prompt,
    entity_extraction_prompt,
    exception_summary_prompt,
    letter_prompt,
)

__all__ = [
    "JSON_SYSTEM_PROMPT",
    "LETTER_SYSTEM_PROMPT",
    "classification_prompt",
    "entity_extraction_prompt",
    "exception_summary_prompt",
    "letter_prompt",
]
