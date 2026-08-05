# Autonomous Enterprise Workflow Agent

An agentic backend that reviews **insurance / healthcare claims** end to end and
pauses for a human only when policy says it must. A claim document (text or PDF)
goes in; the system classifies it, extracts the fields it cares about, runs
layered validation, and either auto-decides or parks the claim for a caseworker —
then resumes from where it left off once the human responds.

It is built as a **LangGraph** state machine behind a **FastAPI** API, with a
static **UI** for claim intake, a workflow queue, and the human-in-the-loop (HITL)
review console. Everything that varies by customer — enabled providers, the
entities to extract, document signals, business rules, and review thresholds — is
**configuration, not code**, so a new tenant is a YAML file rather than a deploy.

## Table of contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
  - [The workflow graph](#the-workflow-graph)
  - [Input guardrail](#input-guardrail)
  - [Validation layers](#validation-layers)
  - [Human-in-the-loop pause / resume](#human-in-the-loop-pause--resume)
  - [LLM providers](#llm-providers)
- [Configuration](#configuration)
- [Run](#run)
- [API](#api)
- [Observability](#observability)
- [Project layout](#project-layout)
- [Design notes](#design-notes)

## What it does

1. **Ingest** a claim as raw text or an uploaded PDF/TXT file.
2. **Classify** whether the document is actually a supported claim (by configured
   document signals).
3. **Extract** the configured entities (policy number, claim amount, claimant,
   provider, service date, …) with confidence and evidence.
4. **Validate** the claim across several layers — extraction quality, business
   rules, and HITL policy.
5. **Decide** automatically (approve / reject) when confidence and rules allow, or
   **pause for human review** when a rule (e.g. a high-value claim) demands it.
6. **Generate** the appropriate correspondence — an approval/rejection letter, or a
   manual-review exception summary.
7. **Audit** every step, and **persist** the whole workflow so a paused claim can be
   resumed later without re-running earlier work.

## How it works

### The workflow graph

The core is a LangGraph `StateGraph` compiled in
[`app/graph/builder.py`](BE/app/graph/builder.py). A shared `WorkflowState` flows
through the nodes; conditional edges decide when to stop early or pause.

```
START
  → document_ingestion            ── unsupported provider ─→ END
  → guardrail_inputs              (redact contact PII before any LLM)
  → document_classification       ── not a claim ──────────→ END
  → entity_extraction
  → extraction_quality_validation
  → business_rule_validation
  → hitl_decision                 ── needs human review ───→ END (paused)
  → letter_or_summary_generation
  → audit_logging
  → END
```

`guardrail_inputs` runs before the first LLM touchpoint and scrubs contact PII
(email, phone, …) from the claim text with regex redaction, so nothing sensitive
leaves the system to an external model — regardless of the configured provider.
See [Input guardrail](#input-guardrail).

When a claim pauses at `hitl_decision`, a second **resume graph**
(`hitl_decision → letter_or_summary_generation → audit_logging`) continues the run
after the caseworker submits their decision.

The live topology is served as Mermaid from `GET /graph` and rendered by the UI at
**`http://127.0.0.1:5173/graph`** — it always reflects the compiled graph, not a
hand-drawn picture.

### Input guardrail

Before the claim text reaches **any** LLM (classification is the first model call),
the `guardrail_inputs` node redacts contact PII so it can never leave the system to
an external provider. Today this is regex-based
([`app/services/input_guardrail.py`](BE/app/services/input_guardrail.py)) covering
email and phone/mobile, replacing each hit with a `[REDACTED_EMAIL]` /
`[REDACTED_PHONE]` placeholder and recording a `GUARDRAIL`-layer finding with the
counts.

Redaction is deliberately scoped to PII that plays **no** part in adjudication —
the claim's own entities (claimant name, policy number, amount, dates, provider) are
left intact so extraction still works. There is a `TODO` in the service to swap in /
augment with a dedicated anonymization service (Microsoft Presidio, AWS Comprehend
PII, GCP DLP) for higher-recall detection of names, addresses, Aadhaar/PAN, and card
numbers.

### Validation layers

Validation is layered, and each layer contributes findings (with a severity) to the
workflow state rather than throwing:

- **Document** — is this a supported claim document at all?
- **Extraction quality** — were the required entities found with enough confidence?
- **Business rules** — tenant rules such as policy-number format or coverage limit.
- **HITL policy** — rules that force human review (e.g. claim amount over a threshold).
- **Final decision** — the terminal status derived from all findings.

Rules are evaluated by the `RuleEngine` from declarative config (regex match,
decimal comparisons, thresholds), so changing a limit is a config edit.

### Human-in-the-loop pause / resume

A pause is **persisted state, not a blocked thread**. When `hitl_decision` routes to
review, the workflow is saved with status `WAITING_FOR_HUMAN_REVIEW` and a review
task attached, and the request returns. A caseworker later calls
`POST /workflows/{id}/review` with `approve` / `reject` / `request_more_info`; the
orchestrator loads the saved state and runs the resume graph to completion. Nothing
earlier in the pipeline re-runs.

State is persisted by `JsonWorkflowStateStore` (the `WorkflowStateStore` interface's
POC implementation) as JSON under `data/workflows/`.

### LLM providers

Document classification, entity extraction, and letter/summary drafting go through a
small `LLMClient` interface with three implementations, chosen per tenant by config:

- **`deterministic`** (default) — regex/rule-based, no API key, fully offline; ideal
  for demos and tests.
- **`openai`** — uses `OPENAI_API_KEY`.
- **`anthropic`** — uses `ANTHROPIC_API_KEY`.

Prompts for all four operations (`classify_document`, `extract_entities`,
`draft_letter`, `draft_exception_summary`) are centralized in
[`app/llm/prompts/`](BE/app/llm/prompts/) so every provider issues identical
instructions. The provider factory wraps the chosen client with observability so
each call is traced and measured (see [Observability](#observability)).

## Configuration

Configuration lives in [`BE/config/`](BE/config):

- `tenants/*.yaml` — one file per tenant/provider: identity, feature flags, the LLM
  provider block, business rules, and HITL rules. See
  [`tenants/default.yaml`](BE/config/tenants/default.yaml).
- `document_types.yaml`, `entity_schema.yaml`, `hitl_policy.yaml`,
  `letter_templates.yaml` — shared defaults a tenant can override.

A tenant config declares, for example, the document signals that mark a valid claim,
the entities to extract, business rules (`POLICY_NUMBER_FORMAT`,
`POLICY_COVERAGE_LIMIT`), and HITL rules (`HIGH_VALUE_CLAIM_REVIEW`). Adding a
customer means adding a YAML file — no code change.

## Run

```bash
  ./start.sh
```

This creates `BE/.venv` and installs backend dependencies on first run, frees
`BE_PORT`/`FE_PORT` if already bound, then starts both servers. Stop with `Ctrl+C`.

Open:

- UI: `http://127.0.0.1:5173`
- Workflow graph: `http://127.0.0.1:5173/graph`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

Ports and hosts are configurable via env vars, e.g. `BE_PORT=8100 FE_PORT=5180 ./start.sh`.
All settings are read from `BE/.env` (copy `BE/.env.example` to `BE/.env`).

### Running BE / UI separately

```bash
  # backend
  cd BE
  python -m venv .venv && source .venv/bin/activate
  pip install -e ".[dev,pdf,observability]"
  python -m uvicorn app.main:app --reload

  # frontend (separate terminal)
  python3 -m http.server 5173 --directory UI
```

## API

| Method & path | Purpose |
| --- | --- |
| `GET /health` | Liveness check. |
| `GET /providers` | List configured tenant/providers. |
| `GET /graph` | LangGraph topology (main + resume) as Mermaid, for the UI. |
| `POST /claims/process` | Process a claim from inline text. |
| `POST /claims/upload` | Process a claim from an uploaded PDF/TXT file. |
| `GET /workflows` | List workflows, optionally filtered by `status`. |
| `GET /workflows/{id}` | Fetch one workflow's full state. |
| `POST /workflows/{id}/review` | Submit a human decision to resume a paused claim. |
| `GET /metrics` | Prometheus metrics (only when `ENABLE_METRICS=true`). |

Process a claim from text:

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

Upload a file instead:

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

## Observability

Two feature flags in `BE/.env` turn on telemetry (both default `false`):

| Flag | Effect |
| --- | --- |
| `ENABLE_TRACING` | OpenTelemetry traces. Auto-instruments FastAPI requests and adds a span per claim (`claim.process` / `claim.resume`), per graph node (`node.*`), and per LLM call (`llm.*`). Exports to `OTEL_EXPORTER_OTLP_ENDPOINT` (OTLP/HTTP) if set, otherwise prints spans to the console. |
| `ENABLE_METRICS` | Prometheus metrics at `GET /metrics`. |

**Trace spans** nest naturally: the request span → `claim.process` → each
`node.<name>` → the `llm.<operation>` calls made inside that node, so a single trace
shows the whole claim, which nodes ran, and every model call with its provider and
model. The noisy/low-value routes `/health`, `/providers`, `/graph`, and `/metrics`
are **excluded** from tracing.

**Metrics** exposed:

| Metric | Labels | Meaning |
| --- | --- | --- |
| `http_requests_total` | `method, path, status` | HTTP requests (path is the route template). |
| `http_request_duration_seconds` | `method, path` | HTTP latency histogram. |
| `claims_processed_total` | `tenant, provider, status` | Claims by terminal status. |
| `claim_processing_duration_seconds` | — | End-to-end claim duration. |
| `workflow_node_runs_total` | `node` | LangGraph node executions. |
| `workflow_node_duration_seconds` | `node` | Per-node execution time. |
| `llm_requests_total` | `provider, operation, model` | LLM calls. |
| `llm_request_errors_total` | `provider, operation` | LLM calls that raised. |
| `llm_request_duration_seconds` | `provider, operation` | LLM call latency. |

The extra dependencies come from the `observability` extra (installed by `start.sh`,
or `pip install -e ".[observability]"`). With the flags off there is no runtime cost
and the packages are not required — every instrumentation helper degrades to a no-op.
To ship traces somewhere real, point `OTEL_EXPORTER_OTLP_ENDPOINT` at an
OpenTelemetry Collector (e.g. `http://localhost:4318/v1/traces`).

## Project layout

```
BE/                         FastAPI + LangGraph backend
  app/
    api/                    routes + request/response schemas
    config/                 tenant config loading
    core/                   settings, DI container, app factory, logging
    domain/                 WorkflowState and domain models
    graph/                  LangGraph builder, state, and nodes
    llm/
      clients/              deterministic / openai / anthropic clients
      factory/              provider factory (selects + instruments a client)
      prompts/              shared prompt templates
    observability/          OTel tracing + Prometheus metrics (flag-gated)
    services/               document loader, rule engine, extractors, etc.
    storage/                workflow state store (JSON)
    workflow/               orchestrator (start / resume)
  config/                   tenant + base YAML configuration
UI/                         static frontend (intake, queue, review, /graph)
data/workflows/             persisted workflow JSON (created at runtime)
start.sh                    runs BE + UI together
```

## Design notes

- `WorkflowStateStore` is the persistence interface; `JsonWorkflowStateStore` is the
  POC implementation.
- Provider enablement, entity definitions, document signals, rules, thresholds, and
  feature flags are all config-driven.
- Validation is layered: document, extraction, business, HITL, and final decision.
- HITL pause is persisted state, not a blocked process, so the API stays responsive
  and paused claims survive restarts.
- Observability is feature-flagged and free when off; instrumentation lives in one
  place (`app/observability/`) and wraps nodes and LLM clients transparently.
