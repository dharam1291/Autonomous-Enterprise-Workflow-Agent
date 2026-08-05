from __future__ import annotations

from app.services.input_guardrail import InputGuardrail


def test_redacts_email_and_phone_but_keeps_claim_fields() -> None:
    guardrail = InputGuardrail()
    text = (
        "Claimant Name: Rahul Sharma\n"
        "Policy Number: ABC-987654\n"
        "Claim Amount: $14500\n"
        "Email: rahul.sharma@example.com\n"
        "Mobile: +91 98765 43210\n"
        "Alt phone: 9123456789\n"
        "Service Date: 2026-07-21\n"
    )

    result = guardrail.redact(text)

    assert result.counts == {"email": 1, "phone": 2}
    # PII gone
    assert "example.com" not in result.text
    assert "43210" not in result.text
    assert "9123456789" not in result.text
    # claim fields untouched
    assert "Rahul Sharma" in result.text
    assert "ABC-987654" in result.text
    assert "14500" in result.text
    assert "2026-07-21" in result.text


def test_no_false_positives_on_dates_amounts_and_policy_numbers() -> None:
    guardrail = InputGuardrail()
    text = "Policy Number: ABC-123456 Claim Amount: $500 Service Date: 2024-01-02 Incident Date: 2023-12-31"

    result = guardrail.redact(text)

    assert result.total == 0
    assert result.text == text
