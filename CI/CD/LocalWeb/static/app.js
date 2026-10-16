const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");
const phaseBadge = document.querySelector("#phase-badge");
const requestForm = document.querySelector("#request-form");
const submitButton = document.querySelector("#submit-button");
const formError = document.querySelector("#form-error");
const imageStyle = document.querySelector("#image-style");
const customImage = document.querySelector("#custom-image");

const STATUS_LABEL = {
  queued: "대기 중",
  running: "실행 중",
  succeeded: "완료",
  failed: "실패",
};
const RESULT_LABEL = {
  game_validation: "게임 검증",
  image_generation: "이미지 생성",
  sound_generation: "사운드 생성",
  final_validation: "최종 검증",
};

let workflowNodes = [];
let workflowReady = false;
let pollTimer = null;
let renderedArtifactsKey = "";

function setText(selector, value) {
  document.querySelector(selector).textContent = value;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function updateCustomImageState() {
  const customSelected = imageStyle.value === "Custom";
  customImage.disabled = !customSelected;
  customImage.required = customSelected;
  if (!customSelected) {
    customImage.value = "";
  }
}

function fillOptions(select, values) {
  const current = select.value;
  select.replaceChildren(...values.map((value) => el("option", "", value)));
  if (values.includes(current)) select.value = current;
}

function setBusy(busy) {
  submitButton.disabled = busy || !workflowReady;
  submitButton.textContent = !workflowReady
    ? "Workflow 연결 후 사용 가능"
    : busy
      ? "Workflow 실행 중…"
      : "Workflow 실행";
}

function showFormError(message) {
  formError.hidden = !message;
  formError.textContent = message || "";
}

async function loadWorkflow() {
  try {
    const [healthResponse, workflowResponse] = await Promise.all([
      fetch("/api/health", { headers: { Accept: "application/json" } }),
      fetch("/api/workflow", { headers: { Accept: "application/json" } }),
    ]);
    if (!healthResponse.ok || !workflowResponse.ok) {
      throw new Error(`health check failed: ${healthResponse.status}/${workflowResponse.status}`);
    }
    const health = await healthResponse.json();
    const workflow = await workflowResponse.json();

    workflowReady = health.workflow === "connected";
    workflowNodes = workflow.nodes;
    fillOptions(imageStyle, workflow.options.image_style);
    fillOptions(document.querySelector("#mood-style"), workflow.options.mood_style);
    fillOptions(document.querySelector("#genre"), workflow.options.genre);
    fillOptions(document.querySelector("#viewpoint"), workflow.options.viewpoint);
    updateCustomImageState();

    statusDot.className = workflowReady
      ? "status-dot status-dot--ready"
      : "status-dot status-dot--error";
    statusText.textContent = workflowReady
      ? `로컬 서버 정상 · Workflow 연결됨 (계약 ${health.contract_version})`
      : `Workflow를 불러오지 못했습니다: ${health.workflow_error}`;
    phaseBadge.textContent = workflowReady ? `Node ${workflowNodes.length}개 연결됨` : "실행 불가";
    setBusy(health.busy);
  } catch (error) {
    statusDot.className = "status-dot status-dot--error";
    statusText.textContent = "로컬 서버 상태를 확인할 수 없습니다.";
    workflowReady = false;
    setBusy(false);
    console.error(error);
  }
}

function elapsed(run) {
  if (!run.started_at) return "-";
  const end = run.finished_at ? new Date(run.finished_at) : new Date();
  return `${((end - new Date(run.started_at)) / 1000).toFixed(1)}초`;
}

function renderNodes(run) {
  const done = new Map(run.events.map((event) => [event.node, event]));
  const list = document.querySelector("#node-list");
  const items = workflowNodes.map((node) => {
    const event = done.get(node);
    const item = el("li", `node-item node-item--${event ? "done" : run.status === "failed" ? "stopped" : "waiting"}`);
    item.append(el("span", "node-mark", event ? "✓" : run.status === "running" ? "…" : "·"));
    item.append(el("span", "node-name", node));
    item.append(el("span", "node-time", event ? `${(event.elapsed_ms / 1000).toFixed(2)}초` : ""));
    return item;
  });
  list.replaceChildren(...items);
}

function renderResults(run) {
  const container = document.querySelector("#result-list");
  const cards = Object.entries(RESULT_LABEL)
    .filter(([key]) => run.results[key])
    .map(([key, label]) => {
      const result = run.results[key];
      const status = result.status || "-";
      const card = el("div", `result-card result-card--${status}`);
      card.append(el("span", "meta-label", label), el("strong", "", status));
      const issues = (result.issues || []).slice(0, 3);
      issues.forEach((issue) => card.append(el("p", "result-issue", `${issue.code}: ${issue.message}`)));
      return card;
    });
  container.replaceChildren(...cards);
}

async function renderArtifacts(run) {
  const container = document.querySelector("#artifact-list");
  if (!run.project_id) {
    container.replaceChildren(el("p", "muted", "프로젝트가 생성되면 파일 목록이 표시됩니다."));
    return;
  }
  const response = await fetch(`/api/runs/${encodeURIComponent(run.run_id)}/artifacts`);
  const artifacts = response.ok ? await response.json() : [];
  // Re-render only when the list changes so audio players keep playing while polling.
  const key = run.run_id + ":" + artifacts.map((artifact) => artifact.artifact_id).join(",");
  if (key === renderedArtifactsKey) return;
  renderedArtifactsKey = key;
  if (!artifacts.length) {
    container.replaceChildren(el("p", "muted", "아직 생성된 파일이 없습니다."));
    return;
  }
  const rows = artifacts.map((artifact) => {
    const url = `/api/runs/${encodeURIComponent(run.run_id)}/artifacts/${encodeURIComponent(artifact.artifact_id)}`;
    const row = el("div", "artifact-row");
    const link = el("a", "artifact-path", artifact.relative_path);
    link.href = url;
    row.append(
      el("span", "artifact-category", artifact.category),
      link,
      el("span", "artifact-size", `${(artifact.size_bytes / 1024).toFixed(1)} KB`),
    );
    if (artifact.media_type.startsWith("audio/")) {
      const player = el("audio", "artifact-audio");
      player.controls = true;
      player.preload = "none";
      player.src = `${url}?inline=true`;
      row.append(player);
    }
    return row;
  });
  container.replaceChildren(...rows);
}

async function renderRun(run) {
  document.querySelector("#empty-state").hidden = true;
  document.querySelector("#run-view").hidden = false;
  setText("#run-id", run.run_id);
  setText("#run-project", run.project_id || "-");
  const outcome =
    run.status === "succeeded" && run.outcome === "game_validation_failed"
      ? "완료 · 게임 검증 실패"
      : STATUS_LABEL[run.status] || run.status;
  setText("#run-status", outcome);
  setText("#run-elapsed", elapsed(run));
  const runError = document.querySelector("#run-error");
  runError.hidden = !run.error;
  runError.textContent = run.error || "";
  renderNodes(run);
  renderResults(run);
  await renderArtifacts(run);
}

async function pollRun(runId) {
  clearTimeout(pollTimer);
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!response.ok) throw new Error(`run lookup failed: ${response.status}`);
    const run = await response.json();
    await renderRun(run);
    const active = run.status === "queued" || run.status === "running";
    setBusy(active);
    if (active) pollTimer = setTimeout(() => pollRun(runId), 1000);
  } catch (error) {
    console.error(error);
    pollTimer = setTimeout(() => pollRun(runId), 3000);
  }
}

async function submitRequest(event) {
  event.preventDefault();
  showFormError("");
  setBusy(true);
  try {
    const response = await fetch("/api/runs", { method: "POST", body: new FormData(requestForm) });
    const body = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(body.detail)
        ? body.detail.map((item) => item.msg).join(", ")
        : body.detail;
      throw new Error(detail || `요청 실패 (${response.status})`);
    }
    pollRun(body.run_id);
  } catch (error) {
    showFormError(error.message);
    setBusy(false);
  }
}

async function restoreLatestRun() {
  const response = await fetch("/api/runs");
  if (!response.ok) return;
  const runs = await response.json();
  if (runs.length) pollRun(runs[0].run_id);
}

imageStyle.addEventListener("change", updateCustomImageState);
requestForm.addEventListener("submit", submitRequest);
updateCustomImageState();
loadWorkflow().then(restoreLatestRun);
