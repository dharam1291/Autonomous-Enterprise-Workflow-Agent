const state = {
  selectedWorkflowId: null,
  workflows: [],
  activeStream: null,
};

const byId = (id) => document.getElementById(id);

// Pipeline stages mirror the LangGraph node order in BE/app/graph/builder.py.
// Each stage is considered "reached" once one of its marker strings appears
// in WorkflowState.audit_events - the same audit trail the API returns for
// every claim, so this is a rendering of BE-reported progress, not a guess.
const PIPELINE_STAGES = [
  { id: "received", label: "Claim Received", markers: ["Workflow received."] },
  {
    id: "document_ingestion",
    label: "Document Ingestion",
    markers: ["Document ingestion completed.", "Provider is disabled by feature flag."],
  },
  {
    id: "document_classification",
    label: "Document Classification",
    markers: ["Document classification started."],
  },
  { id: "entity_extraction", label: "Entity Extraction", markers: ["Entity extraction completed."] },
  {
    id: "extraction_quality_validation",
    label: "Extraction Quality Validation",
    markers: ["Extraction quality validation completed."],
  },
  {
    id: "business_rule_validation",
    label: "Business Validation",
    markers: ["Business rule validation completed."],
  },
  {
    id: "hitl_decision",
    label: "HITL Decision",
    markers: ["HITL policy validation completed.", "Workflow resumed after human review."],
  },
  {
    id: "letter_or_summary_generation",
    label: "Letter / Summary Generation",
    markers: ["Letter or summary generation completed."],
  },
  { id: "audit_logging", label: "Audit Logging", markers: ["Audit logging completed."] },
];

function computeStages(workflow) {
  const events = workflow.audit_events || [];
  const reached = (markers) => markers.some((marker) => events.some((event) => event.includes(marker)));
  const isWaiting = workflow.status === "WAITING_FOR_HUMAN_REVIEW";
  const isInFlight = workflow.status === "RECEIVED" || workflow.status === "PROCESSING";

  let stopped = false;
  return PIPELINE_STAGES.map((stage) => {
    if (stopped) {
      return { ...stage, state: isWaiting || isInFlight ? "pending" : "skipped" };
    }
    const isReached = reached(stage.markers);
    if (stage.id === "hitl_decision" && isWaiting && isReached) {
      stopped = true;
      return { ...stage, state: "waiting" };
    }
    if (isReached) {
      return { ...stage, state: "done" };
    }
    stopped = true;
    return { ...stage, state: isWaiting || isInFlight ? "pending" : "skipped" };
  });
}

function renderStages(workflow) {
  const list = byId("pipeline-stepper");
  list.innerHTML = "";
  if (!workflow) {
    return;
  }
  computeStages(workflow).forEach((stage) => {
    const item = document.createElement("li");
    item.className = `step step-${stage.state}`;
    item.innerHTML = `<span class="step-marker"></span><span class="step-label">${stage.label}</span><span class="step-state">${stepStateLabel(stage.state)}</span>`;
    list.appendChild(item);
  });
}

function stepStateLabel(stepState) {
  switch (stepState) {
    case "done":
      return "Done";
    case "waiting":
      return "Waiting for review";
    case "skipped":
      return "Skipped";
    case "pending":
      return "Pending";
    default:
      return "";
  }
}

async function requestJson(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(`${window.API_BASE_URL}${path}`, {
    headers: isFormData ? options.headers : { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response.json();
}

function setBusy(button, busy) {
  button.disabled = busy;
  button.dataset.originalText ||= button.textContent;
  button.textContent = busy ? "Working..." : button.dataset.originalText;
}

async function checkHealth() {
  try {
    await requestJson("/health");
    byId("health-dot").style.background = "var(--success)";
    byId("health-text").textContent = "API online";
  } catch {
    byId("health-dot").style.background = "var(--danger)";
    byId("health-text").textContent = "API unavailable";
  }
}

async function loadProviders() {
  const providers = await requestJson("/providers");
  const select = byId("provider-select");
  select.innerHTML = "";
  providers.forEach((provider) => {
    const option = document.createElement("option");
    option.value = provider.tenant_id;
    option.textContent = `${provider.display_name}${provider.enabled ? "" : " (disabled)"}`;
    select.appendChild(option);
  });
}

async function loadWorkflows() {
  const status = byId("status-filter").value;
  const url = status ? `/workflows?status=${encodeURIComponent(status)}` : "/workflows";
  state.workflows = await requestJson(url);
  renderWorkflowList();
}

function renderWorkflowList() {
  const list = byId("workflow-list");
  const template = byId("workflow-row-template");
  list.innerHTML = "";

  if (!state.workflows.length) {
    list.innerHTML = "<p class=\"empty-state\">No workflows found.</p>";
    return;
  }

  state.workflows
    .slice()
    .reverse()
    .forEach((workflow) => {
      const row = template.content.firstElementChild.cloneNode(true);
      row.classList.toggle("selected", workflow.workflow_id === state.selectedWorkflowId);
      row.querySelector(".row-id").textContent = workflow.workflow_id;
      const source = row.querySelector(".row-source");
      source.textContent = workflow.source_name;
      source.title = workflow.source_name;
      row.querySelector(".row-status").textContent = workflow.status;
      row.addEventListener("click", () => selectWorkflow(workflow));
      list.appendChild(row);
    });
}

function selectWorkflow(workflow) {
  state.selectedWorkflowId = workflow.workflow_id;
  byId("workflow-title").textContent = workflow.workflow_id;
  byId("workflow-status").textContent = workflow.status;
  byId("recommendation").textContent = workflow.recommendation || "-";
  byId("current-step").textContent = workflow.current_step || "-";
  byId("review-workflow").textContent =
    workflow.status === "WAITING_FOR_HUMAN_REVIEW" ? workflow.workflow_id : "None";

  renderStages(workflow);
  renderEntities(workflow);
  renderFindings(workflow);
  byId("generated-output").textContent =
    workflow.exception_summary || workflow.generated_letter || "-";
  renderWorkflowList();
}

function renderEntities(workflow) {
  const list = byId("entity-list");
  list.innerHTML = "";
  const values = workflow.extracted_entities?.values || {};
  const names = Object.keys(values);

  if (!names.length) {
    list.innerHTML = "<dt>Status</dt><dd>No entities extracted</dd>";
    return;
  }

  names.forEach((name) => {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = name.replaceAll("_", " ");
    dd.textContent = values[name]?.value || "-";
    list.append(dt, dd);
  });
}

function renderFindings(workflow) {
  const list = byId("finding-list");
  list.innerHTML = "";
  const findings = workflow.validation_findings || [];

  if (!findings.length) {
    list.innerHTML = "<li>No findings yet.</li>";
    return;
  }

  findings.slice(-8).forEach((finding) => {
    const item = document.createElement("li");
    item.className = finding.outcome === "FAILED" ? "failed" : "passed";
    item.textContent = `${finding.layer}: ${finding.message}`;
    list.appendChild(item);
  });
}

const ALLOWED_FILE_EXTENSIONS = [".pdf", ".txt"];

function isAllowedFile(file) {
  const name = file.name.toLowerCase();
  return ALLOWED_FILE_EXTENSIONS.some((extension) => name.endsWith(extension));
}

function showFileError(message) {
  const errorEl = byId("file-error");
  errorEl.textContent = message;
  errorEl.hidden = !message;
}

function onFileChosen() {
  const input = byId("document-file");
  const file = input.files[0];
  const chip = byId("file-chip");

  if (!file) {
    chip.hidden = true;
    showFileError("");
    return;
  }

  if (!isAllowedFile(file)) {
    input.value = "";
    chip.hidden = true;
    showFileError("Only .pdf or .txt files are supported.");
    return;
  }

  showFileError("");
  const fileNameEl = byId("file-name");
  fileNameEl.textContent = file.name;
  fileNameEl.title = file.name;
  chip.hidden = false;

  const sourceName = byId("source-name");
  sourceName.value = file.name;
  sourceName.title = file.name;
}

function clearFile() {
  byId("document-file").value = "";
  byId("source-name").value = "";
  onFileChosen();
}

// ── SSE streaming ───────────────────────────────────────────────────

function closeActiveStream() {
  if (state.activeStream) {
    state.activeStream.close();
    state.activeStream = null;
  }
}

function streamWorkflow(workflowId, button) {
  closeActiveStream();

  const source = new EventSource(`${window.API_BASE_URL}/claims/${workflowId}/stream`);
  state.activeStream = source;

  source.addEventListener("node_complete", (event) => {
    const data = JSON.parse(event.data);
    renderStages({ audit_events: data.audit_events, status: data.status });
    byId("workflow-status").textContent = data.status;
    byId("current-step").textContent = data.current_step || "-";
  });

  source.addEventListener("complete", async () => {
    source.close();
    state.activeStream = null;
    await finishStream(workflowId, button);
  });

  source.addEventListener("error", async (event) => {
    if (source.readyState === EventSource.CLOSED) {
      return;
    }
    source.close();
    state.activeStream = null;
    await finishStream(workflowId, button);
  });
}

async function finishStream(workflowId, button) {
  try {
    // Fetch the specific workflow directly — loadWorkflows() respects the status
    // filter, so a just-completed review workflow would be excluded from the
    // filtered list and never selected, leaving generated-output stale.
    const [workflow] = await Promise.all([
      requestJson(`/workflows/${workflowId}`),
      loadWorkflows(),
    ]);
    selectWorkflow(workflow);
  } finally {
    setBusy(button, false);
  }
}

// ── Claim processing (async submit + SSE) ───────────────────────────

async function processClaim(event) {
  event.preventDefault();
  const file = byId("document-file").files[0];

  if (!file) {
    showFileError("Choose a .pdf or .txt claim document to process.");
    return;
  }
  if (!isAllowedFile(file)) {
    showFileError("Only .pdf or .txt files are supported.");
    return;
  }

  const button = event.submitter;
  setBusy(button, true);
  try {
    const tenantId = byId("provider-select").value;
    const formData = new FormData();
    formData.append("file", file);
    const result = await requestJson(
      `/claims/submit?tenant_id=${encodeURIComponent(tenantId)}`,
      { method: "POST", body: formData },
    );

    clearFile();
    selectWorkflow(result.state);
    streamWorkflow(result.workflow_id, button);
  } catch (error) {
    alert(error.message);
    setBusy(button, false);
  }
}

// ── Human review (async submit + SSE) ───────────────────────────────

async function submitReview(event) {
  event.preventDefault();
  const workflow = state.workflows.find((item) => item.workflow_id === state.selectedWorkflowId);
  if (!workflow || workflow.status !== "WAITING_FOR_HUMAN_REVIEW") {
    alert("Select a workflow waiting for human review.");
    return;
  }

  const button = event.submitter;
  setBusy(button, true);
  try {
    const result = await requestJson(`/workflows/${workflow.workflow_id}/review/stream`, {
      method: "POST",
      body: JSON.stringify({
        action: byId("review-action").value,
        reviewer: byId("reviewer").value,
        notes: byId("review-notes").value,
      }),
    });
    selectWorkflow(result.state);
    streamWorkflow(result.workflow_id, button);
  } catch (error) {
    alert(error.message);
    setBusy(button, false);
  }
}

// ── Navigation & boot ───────────────────────────────────────────────

const VIEW_TITLES = {
  intake: "Process Claims",
  workflows: "History",
  review: "Review",
};

function switchView(view) {
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.view === view);
  });
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === view);
  });
  byId("view-title").textContent = VIEW_TITLES[view] || "Process Claims";
  if (view === "review") {
    focusReviewTarget();
  }
}

async function focusReviewTarget() {
  const selected = state.workflows.find((item) => item.workflow_id === state.selectedWorkflowId);
  if (selected && selected.status === "WAITING_FOR_HUMAN_REVIEW") {
    setReviewEmptyState(false);
    return;
  }

  let waiting = [];
  try {
    waiting = await requestJson("/workflows?status=WAITING_FOR_HUMAN_REVIEW");
  } catch (error) {
    waiting = state.workflows.filter((item) => item.status === "WAITING_FOR_HUMAN_REVIEW");
  }

  const target = waiting
    .slice()
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0];

  if (target) {
    selectWorkflow(target);
    setReviewEmptyState(false);
  } else {
    setReviewEmptyState(true);
  }
}

function setReviewEmptyState(isEmpty) {
  const form = byId("review-form");
  const submit = form.querySelector("button[type=submit]");
  byId("review-empty").hidden = !isEmpty;
  if (submit) {
    submit.disabled = isEmpty;
  }
  if (isEmpty) {
    byId("review-workflow").textContent = "None";
  }
}

function wireEvents() {
  byId("claim-form").addEventListener("submit", processClaim);
  byId("review-form").addEventListener("submit", submitReview);
  byId("refresh-button").addEventListener("click", () => window.location.reload());
  byId("status-filter").addEventListener("change", loadWorkflows);
  byId("document-file").addEventListener("change", onFileChosen);
  byId("clear-file").addEventListener("click", clearFile);
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", () => switchView(link.dataset.view));
  });
}

async function boot() {
  wireEvents();
  switchView("intake");
  await Promise.all([checkHealth(), loadProviders(), loadWorkflows()]);
}

boot();
