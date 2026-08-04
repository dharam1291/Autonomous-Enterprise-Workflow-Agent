const samples = {
  approved:
    "Claim Form\nClaimant Name: Rahul Sharma\nPolicy Number: ABC-987654\nClaim Amount: $4500\nReason for Claim: Consultation\nProvider Name: City Health Clinic\nService Date: 2026-07-15\n",
  hitl:
    "Claim Form\nClaimant Name: Rahul Sharma\nPolicy Number: ABC-987654\nClaim Amount: $14500\nReason for Claim: Surgery\nProvider Name: City Hospital\nService Date: 2026-07-15\n",
};

const state = {
  selectedWorkflowId: null,
  workflows: [],
};

const byId = (id) => document.getElementById(id);

async function requestJson(path, options = {}) {
  const response = await fetch(`${window.API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
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
    option.value = provider.provider_id;
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
      row.querySelector(".row-source").textContent = workflow.source_name;
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

async function processClaim(event) {
  event.preventDefault();
  const button = event.submitter;
  setBusy(button, true);
  try {
    const result = await requestJson("/claims/process", {
      method: "POST",
      body: JSON.stringify({
        tenant_id: "default",
        provider_id: byId("provider-select").value,
        source_name: byId("source-name").value,
        document_text: byId("document-text").value,
      }),
    });
    await loadWorkflows();
    selectWorkflow(result.state);
  } catch (error) {
    alert(error.message);
  } finally {
    setBusy(button, false);
  }
}

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
    const result = await requestJson(`/workflows/${workflow.workflow_id}/review`, {
      method: "POST",
      body: JSON.stringify({
        action: byId("review-action").value,
        reviewer: byId("reviewer").value,
        notes: byId("review-notes").value,
      }),
    });
    await loadWorkflows();
    selectWorkflow(result.state);
  } catch (error) {
    alert(error.message);
  } finally {
    setBusy(button, false);
  }
}

function wireEvents() {
  byId("claim-form").addEventListener("submit", processClaim);
  byId("review-form").addEventListener("submit", submitReview);
  byId("refresh-button").addEventListener("click", loadWorkflows);
  byId("status-filter").addEventListener("change", loadWorkflows);
  byId("sample-approved").addEventListener("click", () => {
    byId("document-text").value = samples.approved;
  });
  byId("sample-hitl").addEventListener("click", () => {
    byId("document-text").value = samples.hitl;
  });
}

async function boot() {
  byId("document-text").value = samples.approved;
  wireEvents();
  await Promise.all([checkHealth(), loadProviders(), loadWorkflows()]);
}

boot();
