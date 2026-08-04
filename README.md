# Autonomous Enterprise Workflow Agent

FastAPI POC for an insurance/healthcare claim review workflow. The service ingests claim text, classifies the document, extracts configured entities, applies layered validation, pauses for human review when required, and resumes from persisted JSON workflow state.

## Layout

- `BE/` — FastAPI + LangGraph backend (API, workflow graph, LLM providers, config).
- `UI/` — static frontend (claim intake, workflow queue, HITL review console).

## Run

```bash
./start.sh
```

This creates `BE/.venv` and installs backend dependencies on first run, frees `BE_PORT`/`FE_PORT` if something else is already bound to them, then starts both servers. Stop with `Ctrl+C`.

Open:

- UI: `http://127.0.0.1:5173`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

Ports and hosts are configurable via env vars, e.g. `BE_PORT=8100 FE_PORT=5180 ./start.sh`.

### Running BE/UI separately

```bash
# backend
cd BE
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,pdf]"
python -m uvicorn app.main:app --reload

# frontend (separate terminal)
python3 -m http.server 5173 --directory UI
```

## Example

```bash
curl -X POST http://127.0.0.1:8000/claims/process \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default",
    "provider_id": "default",
    "source_name": "high-value-claim.txt",
    "document_text": "Claim Form\nClaimant Name: Rahul Sharma\nPolicy Number: ABC-987654\nClaim Amount: $14500\nReason for Claim: Surgery and inpatient hospitalization\nProvider Name: Metro Hospital\nService Date: 2026-07-21"
  }'
```

PDF or text files can be uploaded directly instead:

```bash
curl -X POST "http://127.0.0.1:8000/claims/upload?tenant_id=default&provider_id=default" \
  -F "file=@/path/to/claim.pdf"
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

