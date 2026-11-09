const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");
const requestForm = document.querySelector("#request-form");
const imageStyle = document.querySelector("#image-style");
const customImage = document.querySelector("#custom-image");
const modelGrid = document.querySelector("#model-grid");
const modelSettingsContent = document.querySelector("#model-settings-content");
const modelSettingsToggle = document.querySelector("#model-settings-toggle");
const featurePanel = document.querySelector("#feature-panel");
const featureList = document.querySelector("#feature-list");
const featureCount = document.querySelector("#feature-count");
const workflowLog = document.querySelector("#workflow-log");
const phaseBadge = document.querySelector("#phase-badge");
const jobState = document.querySelector("#job-state");
const toast = document.querySelector("#toast");
const openUnityButton = document.querySelector("#open-unity-button");
const previewButton = document.querySelector("#preview-button");
const stopButton = document.querySelector("#stop-button");
const copyLogButton = document.querySelector("#copy-log-button");

const providerLabels = { local: "LocalAI", openai: "OpenAI API", gemini: "Gemini API", vastai: "Vast.ai", placeholder: "Placeholder", procedural: "Procedural", elevenlabs: "ElevenLabs API" };
let currentJobId = null;
let currentJob = null;
let pollTimer = null;

function showToast(message, error = false) {
  toast.textContent = message;
  toast.className = `toast toast--visible${error ? " toast--error" : ""}`;
  window.setTimeout(() => { toast.className = "toast"; }, 3500);
}

function updateCustomImageState() {
  const customSelected = imageStyle.value === "Custom";
  customImage.disabled = !customSelected;
  if (!customSelected) customImage.value = "";
}

function setModelSettingsExpanded(expanded) {
  modelSettingsContent.hidden = !expanded;
  modelSettingsToggle.setAttribute("aria-expanded", String(expanded));
  modelSettingsToggle.textContent = expanded ? "설정 접기" : "설정 펼치기";
}

async function copyWorkflowLog() {
  const text = workflowLog.textContent || "";
  if (!text.trim()) {
    showToast("복사할 작업 로그가 없습니다.", true);
    return;
  }
  let fallback = null;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      fallback = document.createElement("textarea");
      fallback.value = text;
      fallback.setAttribute("readonly", "");
      fallback.className = "clipboard-fallback";
      document.body.append(fallback);
      fallback.select();
      if (!document.execCommand("copy")) throw new Error("clipboard copy rejected");
    }
    showToast("작업 로그를 클립보드에 복사했습니다.");
  } catch (_error) {
    showToast("로그를 복사하지 못했습니다. 로그를 선택해 직접 복사하세요.", true);
  } finally {
    fallback?.remove();
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", Accept: "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `요청 실패 (${response.status})`);
  return payload;
}

function renderCatalog(payload) {
  modelGrid.replaceChildren();
  payload.roles.forEach((role) => {
    const card = document.createElement("article");
    card.className = "model-card";
    card.dataset.role = role.id;
    card.innerHTML = `
      <div class="model-card__heading"><strong>${escapeHtml(role.label)}</strong><span>${escapeHtml(role.id)}</span></div>
      <p>${escapeHtml(role.description)}</p>
      <div class="model-controls">
        <label>Provider<select class="provider-select"></select></label>
        <label>Model<span class="model-control"></span></label>
      </div>`;
    const providerSelect = card.querySelector(".provider-select");
    role.providers.forEach((provider) => providerSelect.add(new Option(providerLabels[provider] || provider, provider)));
    providerSelect.value = role.selection.provider;
    providerSelect.addEventListener("change", () => renderModelControl(card, role));
    modelGrid.append(card);
    renderModelControl(card, role, role.selection.model);
  });
  Object.entries(payload.api_keys).forEach(([provider, state]) => {
    const node = document.querySelector(`#${provider}-key-state`);
    node.textContent = state.configured ? "등록됨" : "미등록";
    node.className = `key-state ${state.configured ? "key-state--ready" : ""}`;
  });
}

function renderModelControl(card, role, selectedModel = "") {
  const provider = card.querySelector(".provider-select").value;
  const host = card.querySelector(".model-control");
  host.replaceChildren();
  if (provider === "local") {
    const select = document.createElement("select");
    select.className = "model-select";
    role.local_models.forEach((model) => select.add(new Option(model, model)));
    select.value = role.local_models.includes(selectedModel) ? selectedModel : role.local_models[0];
    host.append(select);
  } else if (["placeholder", "procedural"].includes(provider)) {
    const input = document.createElement("input");
    input.className = "model-input";
    input.value = provider;
    input.readOnly = true;
    host.append(input);
  } else {
    const input = document.createElement("input");
    input.className = "model-input";
    input.placeholder = provider === "openai" ? "예: gpt-6.1-sol" : provider === "gemini" ? "예: gemini-3-flash-preview" : "서빙 중인 모델 ID";
    input.value = selectedModel && !role.local_models.includes(selectedModel) ? selectedModel : provider === "elevenlabs" ? "auto" : "";
    input.required = true;
    host.append(input);
  }
}

function collectModelSettings() {
  const roles = {};
  document.querySelectorAll(".model-card").forEach((card) => {
    const provider = card.querySelector(".provider-select").value;
    const modelNode = card.querySelector(".model-select, .model-input");
    if (!modelNode.value.trim()) throw new Error(`${card.dataset.role} 모델명을 입력하세요.`);
    roles[card.dataset.role] = { provider, model: modelNode.value.trim() };
  });
  const apiKeys = {};
  ["openai", "gemini", "vastai", "elevenlabs"].forEach((provider) => {
    const value = document.querySelector(`#${provider}-key`).value.trim();
    if (value) apiKeys[provider] = value;
  });
  return { roles, api_keys: apiKeys };
}

async function saveModels({ quiet = false } = {}) {
  const payload = await api("/api/config/models", { method: "PUT", body: JSON.stringify(collectModelSettings()) });
  ["openai", "gemini", "vastai", "elevenlabs"].forEach((provider) => { document.querySelector(`#${provider}-key`).value = ""; });
  renderCatalog(payload);
  if (!quiet) showToast("AI 설정을 저장했습니다.");
}

async function fileToPayload(file) {
  if (!file) return null;
  if (file.size > 10 * 1024 * 1024) throw new Error("Custom 이미지는 10 MiB 이하여야 합니다.");
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return { name: file.name, media_type: file.type, data_base64: btoa(binary) };
}

async function startJob(mode) {
  if (!requestForm.reportValidity()) return;
  setRunButtons(true);
  try {
    await saveModels({ quiet: true });
    const form = new FormData(requestForm);
    const payload = {
      mode,
      game_builder: form.get("game_builder"),
      image_style: form.get("image_style"), mood_style: form.get("mood_style"),
      genre: form.get("genre"), viewpoint: form.get("viewpoint"),
      condition: form.get("condition"),
      custom_image: await fileToPayload(customImage.files[0]),
    };
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    currentJobId = job.job_id;
    featurePanel.classList.add("is-hidden");
    phaseBadge.textContent = "Feature 분석 중";
    workflowLog.textContent = "";
    renderJob(job);
    startPolling();
  } catch (error) {
    showToast(error.message, true);
    setRunButtons(false);
  }
}

function startPolling() {
  window.clearInterval(pollTimer);
  pollTimer = window.setInterval(refreshJob, 1000);
  refreshJob();
}

async function refreshJob() {
  if (!currentJobId) return;
  try {
    const job = await api(`/api/jobs/${currentJobId}`);
    renderJob(job);
    const previewFinished = ["ready", "failed", "cancelled"].includes(job.preview_status);
    if (job.status === "cancelled"
        || (job.status === "failed" && job.preview_status !== "building")
        || (job.status === "completed" && previewFinished)) {
      window.clearInterval(pollTimer);
    }
  } catch (error) {
    window.clearInterval(pollTimer);
    showToast(error.message, true);
  }
}

function renderJob(job) {
  currentJob = job;
  const stateLabels = {
    analyzing_features: "Feature 분석 중", awaiting_confirmation: "사용자 승인 대기",
    running: "게임 생성 중", cancelling: "중단 중", cancelled: "취소됨",
    completed: "완료", failed: "실패",
  };
  const label = stateLabels[job.status] || job.status;
  jobState.textContent = label;
  phaseBadge.textContent = label;
  workflowLog.textContent = job.logs.length ? job.logs.join("\n") : "프로세스를 시작하는 중입니다...";
  workflowLog.scrollTop = workflowLog.scrollHeight;
  if (job.status === "awaiting_confirmation") {
    renderFeatures(job.features);
    featurePanel.classList.remove("is-hidden");
  } else {
    featurePanel.classList.add("is-hidden");
  }
  const previewBuilding = job.preview_status === "building";
  const active = ["analyzing_features", "awaiting_confirmation", "running", "cancelling"].includes(job.status) || previewBuilding;
  setRunButtons(active);
  stopButton.classList.toggle("is-hidden", !active);
  stopButton.disabled = job.status === "cancelling";
  document.querySelector("#confirm-button").disabled = job.status !== "awaiting_confirmation";
  document.querySelector("#reject-button").disabled = job.status !== "awaiting_confirmation";
  const canOpenUnity = ["completed", "failed"].includes(job.status) && Boolean(job.project_id) && !previewBuilding;
  openUnityButton.classList.toggle("is-hidden", !canOpenUnity);
  openUnityButton.disabled = !canOpenUnity;
  renderPreviewButton(job);
  if (job.status === "failed" && job.error) showToast(job.error, true);
}

function renderPreviewButton(job) {
  const canPreview = ["completed", "failed"].includes(job.status) && Boolean(job.project_id);
  previewButton.classList.toggle("is-hidden", !canPreview);
  previewButton.disabled = !canPreview || job.preview_status === "building";
  if (job.preview_status === "ready") {
    previewButton.textContent = "Preview 플레이";
    previewButton.title = job.status === "failed"
      ? "검증에 실패한 현재 Unity 프로젝트를 WebGL로 실행합니다."
      : "완성된 WebGL 게임을 새 탭에서 실행합니다.";
  } else if (job.preview_status === "building") {
    previewButton.textContent = "WebGL Preview 빌드 중…";
    previewButton.title = "Unity가 WebGL 플레이어를 빌드하고 있습니다.";
  } else {
    previewButton.textContent = job.preview_status === "unavailable" ? "Preview 빌드" : "Preview 다시 빌드";
    previewButton.title = job.preview_error || "WebGL Preview 빌드를 다시 시도합니다.";
  }
}

async function stopJob() {
  if (!currentJobId) return;
  stopButton.disabled = true;
  try {
    const job = await api(`/api/jobs/${currentJobId}/cancel`, { method: "POST", body: "{}" });
    renderJob(job);
    window.clearInterval(pollTimer);
    showToast("작업을 중단했습니다.");
  } catch (error) {
    stopButton.disabled = false;
    showToast(error.message, true);
  }
}

async function openUnityEditor() {
  if (!currentJobId) return;
  openUnityButton.disabled = true;
  try {
    await api(`/api/jobs/${currentJobId}/open-unity`, { method: "POST", body: "{}" });
    showToast("Unity Editor를 열었습니다.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    openUnityButton.disabled = false;
  }
}

async function openOrBuildPreview() {
  if (!currentJobId || !currentJob) return;
  if (currentJob.preview_status === "ready" && currentJob.preview_url) {
    window.open(currentJob.preview_url, "_blank", "noopener,noreferrer");
    return;
  }
  previewButton.disabled = true;
  try {
    const job = await api(`/api/jobs/${currentJobId}/build-webgl`, { method: "POST", body: "{}" });
    renderJob(job);
    startPolling();
    showToast("WebGL Preview 빌드를 시작했습니다.");
  } catch (error) {
    previewButton.disabled = false;
    showToast(error.message, true);
  }
}

function renderFeatures(features) {
  featureCount.textContent = `${features.length}개`;
  featureList.replaceChildren();
  features.forEach((feature) => {
    const item = document.createElement("article");
    item.className = "feature-card";
    item.innerHTML = `
      <div><span class="origin origin--${escapeHtml(feature.origin)}">${originLabel(feature.origin)}</span><code>${escapeHtml(feature.feature_id)}</code></div>
      <h3>${escapeHtml(feature.name)}</h3><p>${escapeHtml(feature.description)}</p>
      ${feature.rationale ? `<small>${escapeHtml(feature.rationale)}</small>` : ""}`;
    featureList.append(item);
  });
}

async function decide(action) {
  if (!currentJobId) return;
  document.querySelector("#confirm-button").disabled = true;
  document.querySelector("#reject-button").disabled = true;
  try {
    const job = await api(`/api/jobs/${currentJobId}/${action}`, { method: "POST", body: "{}" });
    renderJob(job);
    startPolling();
  } catch (error) { showToast(error.message, true); }
}

function setRunButtons(disabled) {
  document.querySelector("#generate-button").disabled = disabled;
  document.querySelector("#test-generate-button").disabled = disabled;
}

function originLabel(origin) {
  return { user: "사용자 요청", requirement_dependency: "요청 의존", genre_inferred: "장르 필수" }[origin] || origin;
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = String(value ?? "");
  return node.innerHTML;
}

async function initialize() {
  updateCustomImageState();
  try {
    const [health, models] = await Promise.all([api("/api/health"), api("/api/config/models")]);
    statusDot.className = "status-dot status-dot--ready";
    statusText.textContent = health.workflow === "connected" ? "로컬 서버 · Workflow 연결됨" : "로컬 서버 정상";
    renderCatalog(models);
  } catch (error) {
    statusDot.className = "status-dot status-dot--error";
    statusText.textContent = "로컬 서버 상태를 확인할 수 없습니다.";
    showToast(error.message, true);
  }
}

imageStyle.addEventListener("change", updateCustomImageState);
modelSettingsToggle.addEventListener("click", () => {
  setModelSettingsExpanded(modelSettingsToggle.getAttribute("aria-expanded") !== "true");
});
copyLogButton.addEventListener("click", copyWorkflowLog);
workflowLog.addEventListener("keydown", (event) => {
  const selection = window.getSelection()?.toString() || "";
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c" && !selection) {
    event.preventDefault();
    copyWorkflowLog();
  }
});
requestForm.addEventListener("submit", (event) => event.preventDefault());
document.querySelector("#save-models").addEventListener("click", () => saveModels().catch((error) => showToast(error.message, true)));
document.querySelector("#generate-button").addEventListener("click", () => startJob("generate"));
document.querySelector("#test-generate-button").addEventListener("click", () => startJob("test-generate"));
document.querySelector("#confirm-button").addEventListener("click", () => decide("confirm"));
document.querySelector("#reject-button").addEventListener("click", () => decide("reject"));
openUnityButton.addEventListener("click", openUnityEditor);
previewButton.addEventListener("click", openOrBuildPreview);
stopButton.addEventListener("click", stopJob);
initialize();
