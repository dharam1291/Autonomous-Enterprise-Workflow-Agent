import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";

const API_BASE = (window.API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

mermaid.initialize({
  startOnLoad: false,
  theme: "base",
  securityLevel: "loose",
  flowchart: { curve: "linear", useMaxWidth: true },
  themeVariables: {
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
    primaryColor: "#e8f1f4",
    primaryBorderColor: "#176b87",
    primaryTextColor: "#1e252b",
    lineColor: "#5a6b74",
    tertiaryColor: "#f6f7f9",
  },
});

const root = document.getElementById("graph-root");
const status = document.getElementById("graph-status");

function card(view, slug) {
  return `
    <section class="graph-card">
      <p class="eyebrow">${view.nodes.length} nodes</p>
      <h2>${escapeHtml(view.name)}</h2>
      <div class="diagram" id="diagram-${slug}"></div>
      <div class="node-legend">
        ${view.nodes.map((n) => `<span class="node-chip">${escapeHtml(n)}</span>`).join("")}
      </div>
    </section>`;
}

async function renderDiagram(slug, mermaidText) {
  const { svg } = await mermaid.render(`mermaid-${slug}`, mermaidText);
  document.getElementById(`diagram-${slug}`).innerHTML = svg;
}

function escapeHtml(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

async function load() {
  try {
    const res = await fetch(`${API_BASE}/graph`);
    if (!res.ok) throw new Error(`Backend responded ${res.status}`);
    const data = await res.json();

    root.innerHTML = card(data.main, "main") + card(data.resume, "resume");
    await renderDiagram("main", data.main.mermaid);
    await renderDiagram("resume", data.resume.mermaid);
  } catch (err) {
    root.innerHTML = `<p class="state error">Could not load the graph: ${escapeHtml(
      err.message,
    )}.<br />Make sure the backend is running at ${escapeHtml(API_BASE)}.</p>`;
  }
}

if (status) status.textContent = "Loading graph…";
load();
