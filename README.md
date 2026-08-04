# Autonomous Enterprise Workflow Agent

FastAPI POC for an insurance/healthcare claim review workflow. The service ingests claim text, classifies the document, extracts configured entities, applies layered validation, pauses for human review when required, and resumes from persisted JSON workflow state.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,pdf]"
uvicorn app.main:app --reload
```

Open:

- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## Example

```bash
curl -X POST http://127.0.0.1:8000/claims/process \
  -H "Content-Type: application/json" \
  -d @samples/high_value_claim.json
```

If the response status is `WAITING_FOR_HUMAN_REVIEW`, resume it:

```bash
curl -X POST http://127.0.0.1:8000/workflows/<workflow_id>/review \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","reviewer":"caseworker@example.com","notes":"Approved after document check."}'
```

## Design

- `WorkflowStateStore` is the persistence interface.
- `JsonWorkflowStateStore` is the POC implementation.
- Provider enablement, entity definitions, document signals, rules, thresholds, and feature flags are config-driven.
- Validation is layered: document, extraction, business, HITL, and final decision.
- HITL pause is persisted state, not a blocked process.

