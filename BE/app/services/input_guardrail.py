"""Input guardrail: redact contact PII from raw claim text before it reaches
any LLM (classification, extraction, drafting).

The claim's own entities (claimant name, policy number, amount, dates, provider)
are intentionally *not* redacted here — they are needed downstream. Only contact
PII that plays no part in claim adjudication (email, phone, ...) is scrubbed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Patterns are intentionally specific to avoid clobbering legitimate claim
# fields such as policy numbers (ABC-123456), amounts, or ISO dates.
# Email runs first so its digits can't later look like a phone number.
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    # Indian mobile (optionally +91, optional space/dash splitting the 10 digits)
    # or US-style 3-3-4. Both require a full phone-length run of digits, so ISO
    # dates and short claim amounts won't match.
    "phone": re.compile(
        r"(?<!\d)(?:"
        r"(?:\+?91[-\s]?)?[6-9]\d{4}[-\s]?\d{5}"
        r"|\+?1?[-\s]?\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{4}"
        r")(?!\d)"
    ),
}


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class InputGuardrail:
    """Regex-based PII redactor.

    TODO: replace/augment these regexes with a dedicated anonymization service
    (e.g. Microsoft Presidio, AWS Comprehend PII, or GCP DLP) for higher-recall
    detection of names, addresses, Aadhaar/PAN, SSNs, and card numbers. Keep the
    RedactionResult contract so callers/nodes don't change.
    """

    def redact(self, text: str) -> RedactionResult:
        counts: dict[str, int] = {}
        redacted = text
        for label, pattern in _PII_PATTERNS.items():
            redacted, hits = pattern.subn(f"[REDACTED_{label.upper()}]", redacted)
            if hits:
                counts[label] = hits
        return RedactionResult(text=redacted, counts=counts)
