const STATUS_LABEL = { pass: "PASSED", fail: "FAILED", error: "ERROR", skip: "SKIPPED" };

const form = document.getElementById("scan-form");
const runButton = document.getElementById("run-button");
const statusLine = document.getElementById("status-line");
const errorBanner = document.getElementById("error-banner");
const resultsSection = document.getElementById("results");
const progressFill = document.getElementById("progress-fill");
const summaryEl = document.getElementById("summary");
const scenarioListEl = document.getElementById("scenario-list");
const reportLink = document.getElementById("report-link");

const MODEL_PLACEHOLDERS = {
  openai: "gpt-4o",
  google: "gemini-2.5-flash",
  anthropic: "claude-sonnet-4-5",
  azure: "my-gpt-4o-deployment",
  azure_ai: "my-deployment-name",
};

async function loadProviders() {
  const res = await fetch("/api/providers");
  const providers = await res.json();
  document.querySelectorAll("select.provider").forEach((select) => {
    for (const [value, label] of Object.entries(providers)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.appendChild(option);
    }
    select.addEventListener("change", () => {
      const modelInput = select.closest(".role-card").querySelector(".model");
      modelInput.placeholder = MODEL_PLACEHOLDERS[select.value] || "";
    });
    select.dispatchEvent(new Event("change"));
  });
}

function readRole(card) {
  const q = (sel) => card.querySelector(sel).value.trim();
  return {
    provider: q("select.provider"),
    model: q(".model"),
    api_key: q(".api-key"),
    base_url: q(".base-url") || null,
    api_version: q(".api-version") || null,
  };
}

function buildRequest() {
  const attackerCard = document.querySelector('.role-card[data-role="attacker"]');
  const targetCard = document.querySelector('.role-card[data-role="target"]');
  const judgeCard = document.querySelector('.role-card[data-role="judge"]');

  const maxScenarios = document.getElementById("max-scenarios").value;
  const maxConcurrency = document.getElementById("max-concurrency").value;

  return {
    attacker: readRole(attackerCard),
    target: readRole(targetCard),
    judge: readRole(judgeCard),
    target_system_prompt: document.getElementById("target-system-prompt").value,
    description: document.getElementById("description").value,
    languages: document
      .getElementById("languages")
      .value.split(",")
      .map((s) => s.trim())
      .filter(Boolean),
    target_mode: document.getElementById("target-mode").value,
    max_scenarios: maxScenarios ? Number(maxScenarios) : null,
    seed: Number(document.getElementById("seed").value || 42),
    group_by: document.getElementById("group-by").value || null,
    commercial_use: document.getElementById("commercial-use").checked,
    include_dataset_generators: document.getElementById("include-dataset-generators").checked,
    parallel: document.getElementById("parallel").checked,
    max_concurrency: maxConcurrency ? Number(maxConcurrency) : null,
  };
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.remove("hidden");
}

function clearError() {
  errorBanner.classList.add("hidden");
  errorBanner.textContent = "";
}

function statBlock(counts) {
  const total = counts.pass + counts.fail + counts.error + counts.skip;
  const tiles = [
    ["total", "Total", total],
    ["pass", "Passed", counts.pass],
    ["fail", "Failed", counts.fail],
    ["error", "Errored", counts.error],
    ["skip", "Skipped", counts.skip],
  ];
  summaryEl.innerHTML = tiles
    .map(
      ([cls, label, n]) =>
        `<div class="stat ${cls}"><span class="n">${n}</span><span class="l">${label}</span></div>`
    )
    .join("");
}

function appendScenarioRow(event) {
  const row = document.createElement("div");
  row.className = "scenario-row";
  row.innerHTML = `
    <span class="badge ${event.status}">${STATUS_LABEL[event.status] || event.status}</span>
    <span class="name">${escapeHtml(event.name)}</span>
    <span class="meta">${event.duration_ms}ms</span>
  `;
  scenarioListEl.prepend(row);
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

async function* parseSSE(reader) {
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sepIndex;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (line) {
        yield JSON.parse(line.slice("data: ".length));
      }
    }
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();
  runButton.disabled = true;
  statusLine.textContent = "Generating attack scenarios...";
  resultsSection.classList.remove("hidden");
  reportLink.classList.add("hidden");
  scenarioListEl.innerHTML = "";
  progressFill.style.width = "0%";
  const counts = { pass: 0, fail: 0, error: 0, skip: 0 };
  statBlock(counts);

  let total = 0;
  let completed = 0;

  try {
    const res = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildRequest()),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (HTTP ${res.status})`);
    }

    const reader = res.body.getReader();
    for await (const event of parseSSE(reader)) {
      if (event.type === "generated") {
        total = event.total;
        statusLine.textContent = `Running 0 / ${total} scenarios...`;
      } else if (event.type === "scenario") {
        completed += 1;
        counts[event.status] = (counts[event.status] || 0) + 1;
        statBlock(counts);
        appendScenarioRow(event);
        total = event.total;
        progressFill.style.width = `${(completed / total) * 100}%`;
        statusLine.textContent = `Running ${completed} / ${total} scenarios...`;
      } else if (event.type === "done") {
        statusLine.textContent = `Done in ${(event.duration_ms / 1000).toFixed(1)}s · pass rate ${(event.pass_rate * 100).toFixed(1)}%`;
        progressFill.style.width = "100%";
        reportLink.href = `/api/scan/${event.scan_id}/report`;
        reportLink.classList.remove("hidden");
      } else if (event.type === "error") {
        showError(event.message);
        statusLine.textContent = "Scan failed.";
      }
    }
  } catch (err) {
    showError(err.message || String(err));
    statusLine.textContent = "Scan failed.";
  } finally {
    runButton.disabled = false;
  }
});

loadProviders();
