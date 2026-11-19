const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");
const requestForm = document.querySelector("#request-form");
const imageStyle = document.querySelector("#image-style");
const customImage = document.querySelector("#custom-image");
const customImageHelp = document.querySelector("#custom-image-help");
const modelGrid = document.querySelector("#model-grid");
const modelSettingsContent = document.querySelector("#model-settings-content");
const modelSettingsToggle = document.querySelector("#model-settings-toggle");
const featurePanel = document.querySelector("#feature-panel");
const featureList = document.querySelector("#feature-list");
const featureCount = document.querySelector("#feature-count");
const featureHeading = document.querySelector("#feature-heading");
const featureSectionLabel = document.querySelector("#feature-section-label");
const featureHelp = document.querySelector("#feature-help");
const featureWorkflowState = document.querySelector("#feature-workflow-state");
const featureDecisionArea = document.querySelector("#feature-decision-area");
const rejectFeedback = document.querySelector("#reject-feedback");
const gameAssembly = document.querySelector("#game-assembly");
const gameAssemblyStatus = document.querySelector("#game-assembly-status");
const gameAssemblySteps = document.querySelector("#game-assembly-steps");
const workflowLog = document.querySelector("#workflow-log");
const phaseBadge = document.querySelector("#phase-badge");
const jobState = document.querySelector("#job-state");
const toast = document.querySelector("#toast");
const openUnityButton = document.querySelector("#open-unity-button");
const previewButton = document.querySelector("#preview-button");
const stopButton = document.querySelector("#stop-button");
const copyLogButton = document.querySelector("#copy-log-button");
const progressLabel = document.querySelector("#progress-label");
const progressPercent = document.querySelector("#progress-percent");
const progressFill = document.querySelector("#progress-fill");
const progressTrack = document.querySelector(".workflow-progress__track");
const progressTime = document.querySelector("#progress-time");
const completionNotifications = document.querySelector("#completion-notifications");
const notificationStatus = document.querySelector("#notification-status");
const gameBuilder = document.querySelector("#game-builder");
const agentHarnessSettings = document.querySelector("#agent-harness-settings");
const agentModel = document.querySelector("#agent-model");
const agentReasoningEffort = document.querySelector("#agent-reasoning-effort");
const agentFastMode = document.querySelector("#agent-fast-mode");
const agentFastModeField = document.querySelector("#agent-fast-mode-field");
const agentSettingsHelp = document.querySelector("#agent-settings-help");
const codexAuthPanel = document.querySelector("#codex-auth-panel");
const codexAuthState = document.querySelector("#codex-auth-state");
const codexAuthMessage = document.querySelector("#codex-auth-message");
const codexLoginButton = document.querySelector("#codex-login-button");
const codexLogoutButton = document.querySelector("#codex-logout-button");
const codexAuthLink = document.querySelector("#codex-auth-link");
const codexDeviceDetails = document.querySelector("#codex-device-details");
const codexDeviceCode = document.querySelector("#codex-device-code");
const codexAuthOutput = document.querySelector("#codex-auth-output");

const providerLabels = { codex_cli: "Codex CLI", local: "LocalAI", openai: "OpenAI API", gemini: "Gemini API", vastai: "Vast.ai", placeholder: "Placeholder", procedural: "Procedural", elevenlabs: "ElevenLabs API" };
const notificationSettingKey = "mainflow.completionNotifications";
const agentHarnessCatalog = {
  codex_cli: {
    models: [
      ["default", "기본 · 추천 모델 세트"],
      ["gpt-6.1-sol", "GPT-6.1 Sol · 고성능"],
      ["gpt-6-astra", "GPT-6 Astra · 최고 난도"],
      ["gpt-6.1-terra", "GPT-6.1 Terra · 빠른 정밀 작업"],
      ["gpt-6-sol", "GPT-6 Sol · 고성능"],
      ["gpt-6-luna", "GPT-6 Luna · 속도·비용 우선"],
      ["gpt-5.6-sol", "GPT-5.6 Sol"],
      ["gpt-5.6-terra", "GPT-5.6 Terra"],
      ["gpt-5.6-luna", "GPT-5.6 Luna"],
    ],
    efforts: ["low", "medium", "high", "xhigh", "max"],
    defaultModel: "gpt-5.6-luna",
    defaultEffort: "medium",
    help: "Codex CLI의 작업별 모델과 model_reasoning_effort를 지정합니다. Fast mode는 지원 모델에서 더 빠른 service tier를 사용하며 추가 사용량 또는 비용이 발생할 수 있습니다.",
  },
  claude_code: {
    models: [
      ["sonnet", "Claude Sonnet · 균형형"],
      ["opus", "Claude Opus · 품질 우선"],
      ["haiku", "Claude Haiku · 속도 우선"],
    ],
    efforts: ["low", "medium", "high", "xhigh", "max"],
    defaultModel: "sonnet",
    defaultEffort: "medium",
    help: "Claude Code CLI의 모델 alias와 --effort를 지정합니다. Claude Code에는 Codex Fast service tier 토글을 적용하지 않습니다.",
  },
};
const agentHarnessSelections = {};
let activeAgentBuilder = null;
let currentJobId = null;
let currentJob = null;
let pollTimer = null;
let notificationAudioContext = null;
let notificationWorkerPromise = null;
let notifiedMilestones = new Set();
let toastTimer = null;
let codexAuthPollTimer = null;
let codexAuthenticated = false;
let expandedFeatureIds = new Set();
let lastFeatureRenderKey = null;
let featureViewMode = "cards";
let featureMergeTimer = null;

function showToast(message, error = false) {
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.className = `toast toast--visible${error ? " toast--error" : ""}`;
  toastTimer = window.setTimeout(() => { toast.className = "toast"; }, error ? 8000 : 3500);
}

function replaceSelectOptions(select, entries, selectedValue) {
  select.replaceChildren();
  entries.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === selectedValue;
    select.append(option);
  });
}

function updateAgentHarnessSettings() {
  if (activeAgentBuilder && agentHarnessCatalog[activeAgentBuilder]) {
    agentHarnessSelections[activeAgentBuilder] = {
      model: agentModel.value,
      effort: agentReasoningEffort.value,
    };
  }
  const builder = gameBuilder.value;
  const catalog = agentHarnessCatalog[builder];
  agentHarnessSettings.hidden = !catalog;
  if (!catalog) {
    activeAgentBuilder = null;
    return;
  }
  const saved = agentHarnessSelections[builder] || {};
  replaceSelectOptions(agentModel, catalog.models, saved.model || catalog.defaultModel);
  replaceSelectOptions(
    agentReasoningEffort,
    catalog.efforts.map((effort) => [effort, effort]),
    saved.effort || catalog.defaultEffort,
  );
  agentFastModeField.hidden = builder !== "codex_cli";
  agentSettingsHelp.textContent = catalog.help;
  activeAgentBuilder = builder;
}

function notificationSettingEnabled() {
  return Boolean(completionNotifications?.checked);
}

function saveNotificationSetting() {
  try {
    window.localStorage.setItem(notificationSettingKey, String(notificationSettingEnabled()));
  } catch (_error) {
    // Private browser sessions may reject localStorage; the current-page setting still works.
  }
}

function restoreNotificationSetting() {
  try {
    completionNotifications.checked = window.localStorage.getItem(notificationSettingKey) === "true";
  } catch (_error) {
    completionNotifications.checked = false;
  }
  updateNotificationStatus();
}

function updateNotificationStatus() {
  if (!notificationSettingEnabled()) {
    notificationStatus.textContent = "알림 꺼짐";
  } else if (!("Notification" in window) || !window.isSecureContext) {
    notificationStatus.textContent = "소리만 · Chrome 알림 사용 불가";
  } else if (Notification.permission === "granted") {
    notificationStatus.textContent = "소리 · Chrome 알림 허용됨";
  } else if (Notification.permission === "denied") {
    notificationStatus.textContent = "소리만 · Chrome 알림 차단됨";
  } else {
    notificationStatus.textContent = "소리 · Chrome 알림 권한 요청";
  }
}

async function notificationWorker() {
  if (!window.isSecureContext || !("serviceWorker" in navigator)) return null;
  if (!notificationWorkerPromise) {
    notificationWorkerPromise = navigator.serviceWorker.register("/notification-sw.js")
      .then(() => Promise.race([
        navigator.serviceWorker.ready,
        new Promise((_, reject) => window.setTimeout(() => reject(new Error("알림 서비스 준비 시간 초과")), 5000)),
      ]))
      .catch((error) => {
        console.warn("Chrome 알림 서비스를 시작하지 못했습니다.", error);
        notificationWorkerPromise = null;
        return null;
      });
  }
  return notificationWorkerPromise;
}

async function prepareCompletionNotifications({ requestPermission = false } = {}) {
  if (!notificationSettingEnabled()) return;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  try {
    if (AudioContextClass && !notificationAudioContext) {
      notificationAudioContext = new AudioContextClass();
    }
  } catch (_error) {
    notificationAudioContext = null;
  }
  const resumeAudio = notificationAudioContext?.state === "suspended"
    ? notificationAudioContext.resume().catch(() => {})
    : Promise.resolve();
  if (requestPermission && "Notification" in window) {
    if (Notification.permission === "default") {
      const permission = await Notification.requestPermission().catch(() => "denied");
      if (permission !== "granted") {
        showToast("Chrome 알림 권한이 없어 소리 알림만 사용합니다.");
      }
    } else if (Notification.permission === "denied") {
      showToast("Chrome 알림이 차단되어 소리 알림만 사용합니다.");
    }
  } else if (requestPermission && !("Notification" in window)) {
    showToast("이 브라우저는 시스템 알림을 지원하지 않아 소리만 사용합니다.");
  }
  updateNotificationStatus();
  if ("Notification" in window && Notification.permission === "granted") {
    void notificationWorker();
  }
  await resumeAudio;
}

async function playNotificationTone(kind) {
  if (!notificationSettingEnabled()) return;
  try {
    await prepareCompletionNotifications();
    const context = notificationAudioContext;
    if (!context || context.state !== "running") return;
    const frequencies = kind === "feature"
      ? [659, 880]
      : kind === "success"
        ? [523, 659, 784]
        : [440, 330, 247];
    const now = context.currentTime;
    frequencies.forEach((frequency, index) => {
      const start = now + index * 0.13;
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = kind === "failure" ? "triangle" : "sine";
      oscillator.frequency.setValueAtTime(frequency, start);
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.12, start + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.18);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + 0.2);
    });
  } catch (_error) {
    // Notifications must never interrupt job polling or rendering.
  }
}

async function showSystemNotification(title, body, tag) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const registration = await notificationWorker();
    if (registration?.showNotification) {
      await registration.showNotification(title, { body, tag, renotify: true });
      return;
    }
  } catch (error) {
    console.warn("Chrome 서비스 워커 알림을 표시하지 못했습니다.", error);
  }
  try {
    const notification = new Notification(title, { body, tag, renotify: true });
    notification.addEventListener("click", () => {
      window.focus();
      notification.close();
    });
  } catch (error) {
    console.warn("Chrome 알림을 표시하지 못했습니다.", error);
    showToast("Chrome 알림을 표시하지 못했습니다. 사이트 및 Windows 알림 권한을 확인하세요.");
  }
}

function notifyJobMilestone(job, milestone) {
  if (!notificationSettingEnabled()) return;
  const key = `${job.job_id || currentJobId}:${milestone}`;
  if (notifiedMilestones.has(key)) return;
  notifiedMilestones.add(key);
  if (milestone === "feature") {
    void playNotificationTone("feature");
    void showSystemNotification(
      "겜만툴 · Feature 분석 완료",
      `${job.features.length}개 Feature를 확인하고 Confirm 또는 Reject를 선택하세요.`,
      key,
    );
    return;
  }
  const succeeded = job.status === "completed";
  const cancelled = job.status === "cancelled";
  void playNotificationTone(succeeded ? "success" : "failure");
  void showSystemNotification(
    succeeded ? "겜만툴 · 게임 생성 완료" : cancelled ? "겜만툴 · 작업 중단" : "겜만툴 · 게임 생성 실패",
    succeeded
      ? `프로젝트 ${job.project_id || ""} 생성이 완료되었습니다.`
      : cancelled
        ? "요청한 게임 생성 작업이 중단되었습니다."
        : `프로젝트 ${job.project_id || ""} 생성이 실패했습니다. 개발 로그를 확인하세요.`,
    key,
  );
}

function updateCustomImageState() {
  const customSelected = imageStyle.value === "Custom";
  customImage.required = customSelected;
  customImageHelp.textContent = customSelected
    ? "Custom 스타일에는 PNG/JPG 참고 이미지가 반드시 필요합니다."
    : "선택한 스타일과 함께 캐릭터·배경·색감 참고 자료로 전달합니다.";
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

function formatApiError(payload, status) {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return String(item);
      const location = Array.isArray(item.loc)
        ? item.loc.filter((part) => part !== "body").join(".")
        : "";
      const message = item.msg || item.message || JSON.stringify(item);
      return location ? `${location}: ${message}` : message;
    }).filter(Boolean);
    if (messages.length) return messages.join("\n");
  }
  if (detail && typeof detail === "object") {
    return detail.message || JSON.stringify(detail);
  }
  return `요청 실패 (${status})`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", Accept: "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiError(payload, response.status));
  return payload;
}

function renderCodexAuth(payload) {
  codexAuthenticated = Boolean(payload.authenticated);
  const labels = {
    authenticated: "로그인 완료",
    pending: "로그인 대기",
    signed_out: "로그인 필요",
    failed: "로그인 실패",
    unavailable: "CLI 없음",
  };
  codexAuthState.textContent = labels[payload.phase] || "확인 필요";
  codexAuthState.className = `phase-badge${payload.authenticated ? " phase-badge--ready" : (["failed", "unavailable"].includes(payload.phase) ? " phase-badge--error" : "")}`;
  codexAuthMessage.textContent = payload.version
    ? `${payload.message} · ${payload.version}`
    : payload.message;

  const pending = payload.phase === "pending";
  codexLoginButton.disabled = !payload.installed || pending || payload.authenticated;
  codexLoginButton.textContent = payload.authenticated
    ? "Codex 로그인 완료"
    : (pending ? "로그인 완료 대기 중…" : "Device Code로 로그인");
  codexLogoutButton.hidden = !payload.authenticated;
  codexLogoutButton.disabled = !payload.authenticated;
  codexAuthLink.classList.toggle("is-hidden", !payload.auth_url);
  if (payload.auth_url) codexAuthLink.href = payload.auth_url;
  else codexAuthLink.removeAttribute("href");
  codexDeviceDetails.hidden = !pending;
  codexDeviceCode.textContent = payload.device_code || "코드 대기 중";
  codexAuthOutput.textContent = payload.output || "Codex CLI가 로그인 주소와 코드를 준비하고 있습니다.";

  if (!pending) window.clearInterval(codexAuthPollTimer);
}

async function refreshCodexAuth() {
  try {
    const payload = await api("/api/codex/auth");
    renderCodexAuth(payload);
  } catch (error) {
    codexAuthenticated = false;
    codexAuthState.textContent = "확인 실패";
    codexAuthState.className = "phase-badge phase-badge--error";
    codexAuthMessage.textContent = error.message;
    codexLoginButton.disabled = true;
  }
}

function startCodexAuthPolling() {
  window.clearInterval(codexAuthPollTimer);
  codexAuthPollTimer = window.setInterval(refreshCodexAuth, 1500);
  refreshCodexAuth();
}

async function startCodexDeviceLogin() {
  codexLoginButton.disabled = true;
  try {
    const payload = await api("/api/codex/auth/device", { method: "POST", body: "{}" });
    renderCodexAuth(payload);
    startCodexAuthPolling();
  } catch (error) {
    showToast(error.message, true);
    await refreshCodexAuth();
  }
}

async function logoutCodex() {
  if (!window.confirm("Docker에 저장된 Codex 로그인 정보를 삭제할까요?")) return;
  codexLogoutButton.disabled = true;
  try {
    const payload = await api("/api/codex/auth/logout", { method: "POST", body: "{}" });
    renderCodexAuth(payload);
    showToast("Codex에서 로그아웃했습니다.");
  } catch (error) {
    showToast(error.message, true);
    await refreshCodexAuth();
  }
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
  } else if (provider === "codex_cli") {
    const input = document.createElement("input");
    input.className = "model-input";
    input.value = selectedModel && !role.local_models.includes(selectedModel) ? selectedModel : "builder";
    input.title = "builder: 게임 구현 방식에서 선택한 Codex 모델 사용";
    host.append(input);
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
  if (notificationSettingEnabled()) void prepareCompletionNotifications({ requestPermission: true });
  const form = new FormData(requestForm);
  if (form.get("game_builder") === "codex_cli" && !codexAuthenticated) {
    codexAuthPanel.scrollIntoView({ behavior: "smooth", block: "center" });
    showToast("Codex CLI를 선택하려면 먼저 Docker 내부 Codex에 로그인하세요.", true);
    return;
  }
  setRunButtons(true);
  try {
    await saveModels({ quiet: true });
    const payload = {
      mode,
      game_builder: form.get("game_builder"),
      agent_model: form.get("agent_model") || null,
      agent_reasoning_effort: form.get("agent_reasoning_effort") || null,
      agent_fast_mode: form.get("game_builder") === "codex_cli" && agentFastMode.checked,
      image_style: form.get("image_style"), mood_style: form.get("mood_style"),
      genre: form.get("genre"), viewpoint: form.get("viewpoint"),
      condition: form.get("condition"),
      custom_image: await fileToPayload(customImage.files[0]),
    };
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    currentJobId = job.job_id;
    notifiedMilestones = new Set();
    expandedFeatureIds = new Set();
    lastFeatureRenderKey = null;
    featureViewMode = "cards";
    window.clearTimeout(featureMergeTimer);
    rejectFeedback.value = "";
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
    const details = encodeURIComponent([...expandedFeatureIds].join(","));
    const job = await api(`/api/jobs/${currentJobId}?detail_features=${details}`);
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
  renderProgress(job);
  if (job.features?.length) {
    renderFeatureWorkspace(job);
    featurePanel.classList.remove("is-hidden");
    if (job.status === "awaiting_confirmation") notifyJobMilestone(job, "feature");
  } else {
    featurePanel.classList.add("is-hidden");
  }
  if (["completed", "failed", "cancelled"].includes(job.status)) {
    notifyJobMilestone(job, "terminal");
  }
  const previewBuilding = job.preview_status === "building";
  const active = ["analyzing_features", "awaiting_confirmation", "running", "cancelling"].includes(job.status) || previewBuilding;
  setRunButtons(active);
  stopButton.classList.toggle("is-hidden", !active);
  stopButton.disabled = job.status === "cancelling";
  document.querySelector("#confirm-button").disabled = job.status !== "awaiting_confirmation";
  document.querySelector("#reject-button").disabled = job.status !== "awaiting_confirmation";
  rejectFeedback.disabled = job.status !== "awaiting_confirmation";
  const canOpenUnity = ["completed", "failed"].includes(job.status) && Boolean(job.project_id) && !previewBuilding;
  openUnityButton.classList.toggle("is-hidden", !canOpenUnity);
  openUnityButton.disabled = !canOpenUnity;
  renderPreviewButton(job);
  if (job.status === "failed" && job.error) showToast(job.error, true);
}

function formatDuration(totalSeconds) {
  if (!Number.isFinite(totalSeconds)) return "--:--";
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return hours > 0
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function renderProgress(job) {
  const previewBuilding = job.preview_status === "building";
  const percentValue = previewBuilding ? job.preview_progress_percent : job.progress_percent;
  const label = previewBuilding ? job.preview_progress_label : job.progress_label;
  const elapsedValue = previewBuilding ? job.preview_elapsed_seconds : job.elapsed_seconds;
  const estimateValue = previewBuilding
    ? job.preview_estimated_total_seconds
    : job.estimated_total_seconds;
  const percent = Math.min(100, Math.max(0, Number(percentValue) || 0));
  progressLabel.textContent = label || "처리 중";
  progressPercent.textContent = `${percent}%`;
  progressFill.style.width = `${percent}%`;
  progressTrack.setAttribute("aria-valuenow", String(percent));
  const elapsed = formatDuration(Number(elapsedValue));
  const estimate = estimateValue == null
    ? "사용자 승인 대기"
    : `예상 ${formatDuration(Number(estimateValue))}`;
  progressTime.textContent = `처리 시간 ${elapsed} / ${estimate}`;
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
    const result = await api(`/api/jobs/${currentJobId}/open-unity`, { method: "POST", body: "{}" });
    if (result.status === "launcher_required" && result.launcher_url) {
      const link = document.createElement("a");
      link.href = result.launcher_url;
      link.download = "";
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast("Windows용 Unity 실행 파일을 받았습니다. 다운로드된 .cmd 파일을 실행하세요.");
    } else {
      showToast("Unity Editor를 열었습니다.");
    }
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

function renderFeatureWorkspace(job) {
  const cards = job.feature_cards?.length ? job.feature_cards : job.features;
  const awaiting = job.status === "awaiting_confirmation";
  featureCount.textContent = `${cards.length}개`;
  featureDecisionArea.classList.toggle("is-hidden", !awaiting);
  featureHeading.textContent = awaiting ? "조합 예정 Feature" : "Feature 개발 현황";
  featureSectionLabel.textContent = awaiting ? "APPROVAL GATE" : "FEATURE WORKSPACE";
  featureHelp.textContent = awaiting
    ? "목록을 승인하거나, 수정할 내용을 한마디로 입력한 뒤 Reject해 다시 분석하세요."
    : "각 카드를 눌러 생성된 Checklist와 Unity 검증 결과를 확인할 수 있습니다.";

  let workflowLabel = "Feature 작업 중";
  let workflowClass = "phase-badge";
  if (awaiting) workflowLabel = "승인 대기";
  else if (job.status === "analyzing_features") workflowLabel = "피드백 반영 중";
  else if (job.feature_validation_complete) {
    workflowLabel = "기능 검증 완료";
    workflowClass += " phase-badge--ready";
  } else if (job.status === "failed") {
    workflowLabel = "기능 검증 실패";
    workflowClass += " phase-badge--error";
  }
  featureWorkflowState.textContent = workflowLabel;
  featureWorkflowState.className = workflowClass;

  const shouldAssemble = job.feature_validation_complete
    && !["analyzing_features", "awaiting_confirmation"].includes(job.status);
  if (!shouldAssemble) {
    featureViewMode = "cards";
    window.clearTimeout(featureMergeTimer);
    featureList.classList.remove("is-hidden", "feature-list--merging");
    gameAssembly.classList.add("is-hidden");
    renderFeatures(cards);
    return;
  }
  if (featureViewMode === "cards") {
    renderFeatures(cards);
    beginFeatureMerge(job);
    return;
  }
  if (featureViewMode === "assembly") {
    featureList.classList.add("is-hidden");
    gameAssembly.classList.remove("is-hidden");
    renderGameAssembly(job);
  }
}

function renderFeatures(features) {
  const renderKey = JSON.stringify([features, [...expandedFeatureIds].sort()]);
  if (renderKey === lastFeatureRenderKey && featureList.childElementCount === features.length) return;
  const openCriteria = new Set(
    [...featureList.querySelectorAll(".checklist-item details[open]")].map((details) => {
      const card = details.closest(".feature-card");
      const criterion = details.closest(".checklist-item");
      return `${card?.dataset.featureId}:${criterion?.dataset.criterionId}`;
    }),
  );
  featureList.replaceChildren();
  features.forEach((feature, index) => {
    const featureId = String(feature.feature_id || "feature");
    const status = feature.status || "pending";
    const expanded = expandedFeatureIds.has(featureId);
    const checklist = Array.isArray(feature.checklist) ? feature.checklist : [];
    const checklistItems = checklist.length
      ? checklist.map((criterion) => renderChecklistCriterion(criterion)).join("")
      : `<p class="feature-checklist__empty">${checklistEmptyLabel(feature.checklist_status)}</p>`;
    const item = document.createElement("article");
    item.className = `feature-card feature-card--${escapeHtml(status)}`;
    item.dataset.featureId = featureId;
    item.dataset.checklistCount = String(feature.checklist_count || 0);
    item.style.setProperty("--card-index", String(index));
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.setAttribute("aria-expanded", String(expanded));
    item.innerHTML = `
      <div class="feature-card__top">
        <span class="origin origin--${escapeHtml(feature.origin)}">${originLabel(feature.origin)}</span>
        <code>${escapeHtml(featureId)}</code>
      </div>
      <div class="feature-card__status">
        <span class="feature-status-dot${["working", "retrying"].includes(status) ? " feature-status-dot--spinning" : ""}" aria-hidden="true"></span>
        <strong>${featureStatusLabel(status)}</strong>
        ${feature.validation_attempt ? `<small>${escapeHtml(feature.validation_attempt)}차 검증</small>` : ""}
      </div>
      <h3>${escapeHtml(feature.name)}</h3>
      <p>${escapeHtml(feature.description)}</p>
      ${feature.rationale ? `<small class="feature-card__rationale">${escapeHtml(feature.rationale)}</small>` : ""}
      <p class="feature-card__activity">${escapeHtml(feature.activity || "작업 준비")}</p>
      <button class="feature-card__toggle" type="button" aria-expanded="${expanded}">
        Checklist ${escapeHtml(feature.checklist_count || 0)}개 ${expanded ? "접기" : "보기"}
      </button>
      <div class="feature-checklist${expanded ? "" : " is-hidden"}">
        <div class="feature-checklist__heading">
          <strong>${checklistStatusLabel(feature.checklist_status)}</strong>
          <span>${escapeHtml(feature.checklist_count || 0)} / 30</span>
        </div>
        <ol>${checklistItems}</ol>
      </div>`;
    featureList.append(item);
  });
  featureList.querySelectorAll(".checklist-item").forEach((criterion) => {
    const card = criterion.closest(".feature-card");
    if (openCriteria.has(`${card?.dataset.featureId}:${criterion.dataset.criterionId}`)) {
      criterion.querySelector("details").open = true;
    }
  });
  lastFeatureRenderKey = renderKey;
}

function renderChecklistCriterion(criterion) {
  const status = criterion.status || "pending";
  return `<li class="checklist-item checklist-item--${escapeHtml(status)}" data-criterion-id="${escapeHtml(criterion.criterion_id)}">
    <details>
      <summary>
        <span>${escapeHtml(criterion.criterion_id)} · ${escapeHtml(criterion.title)}</span>
        <em>${checklistResultLabel(status)}</em>
      </summary>
      <dl>
        <div><dt>준비</dt><dd>${escapeHtml(criterion.setup)}</dd></div>
        <div><dt>동작</dt><dd>${escapeHtml(criterion.action)}</dd></div>
        <div><dt>기대 결과</dt><dd>${escapeHtml(criterion.expected)}</dd></div>
        <div><dt>증거</dt><dd>${escapeHtml(criterion.evidence)}</dd></div>
        ${criterion.message ? `<div><dt>검증 결과</dt><dd>${escapeHtml(criterion.message)}</dd></div>` : ""}
      </dl>
    </details>
  </li>`;
}

function featureStatusLabel(status) {
  return {
    pending: "승인 대기",
    working: "작업 중",
    retrying: "수정 후 재검증 중",
    passed: "검증 성공",
    failed: "검증 실패",
  }[status] || "상태 확인 중";
}

function checklistStatusLabel(status) {
  return {
    pending: "Checklist 작성 대기",
    writing: "Checklist 작성 중",
    ready: "Checklist 작성 완료",
    retrying: "실패 항목 재검증 중",
    passed: "전체 Checklist 통과",
    failed: "Checklist 검증 실패",
    not_generated: "동적 Checklist 없음",
  }[status] || "Checklist 상태 확인 중";
}

function checklistEmptyLabel(status) {
  return status === "writing"
    ? "Feature에 맞는 30개 검증 항목을 작성하고 있습니다."
    : "Checklist가 생성되면 이 영역에서 바로 확인할 수 있습니다.";
}

function checklistResultLabel(status) {
  return { passed: "통과", skipped: "통과", failed: "실패", error: "오류", pending: "대기" }[status] || status;
}

function toggleFeatureCard(card) {
  const featureId = card.dataset.featureId;
  if (!featureId) return;
  if (expandedFeatureIds.has(featureId)) expandedFeatureIds.delete(featureId);
  else expandedFeatureIds.add(featureId);
  const expanded = expandedFeatureIds.has(featureId);
  card.setAttribute("aria-expanded", String(expanded));
  card.querySelector(".feature-card__toggle").setAttribute("aria-expanded", String(expanded));
  card.querySelector(".feature-card__toggle").textContent = `Checklist ${card.dataset.checklistCount}개 ${expanded ? "접기" : "보기"}`;
  card.querySelector(".feature-checklist").classList.toggle("is-hidden", !expanded);
  if (expanded) refreshJob();
}

function beginFeatureMerge(job) {
  featureViewMode = "merging";
  featureDecisionArea.classList.add("is-hidden");
  requestAnimationFrame(() => {
    const listRect = featureList.getBoundingClientRect();
    const centerX = listRect.left + listRect.width / 2;
    const centerY = listRect.top + listRect.height / 2;
    featureList.querySelectorAll(".feature-card").forEach((card) => {
      const rect = card.getBoundingClientRect();
      card.style.setProperty("--merge-x", `${centerX - (rect.left + rect.width / 2)}px`);
      card.style.setProperty("--merge-y", `${centerY - (rect.top + rect.height / 2)}px`);
    });
    featureList.classList.add("feature-list--merging");
  });
  featureMergeTimer = window.setTimeout(() => {
    if (currentJobId !== job.job_id) return;
    featureViewMode = "assembly";
    featureList.classList.add("is-hidden");
    gameAssembly.classList.remove("is-hidden");
    renderGameAssembly(currentJob || job);
  }, 900);
}

function renderGameAssembly(job) {
  const steps = ["compose", "assets", "finalize", "preview"];
  let currentIndex = 0;
  if (Number(job.progress_percent) >= 68) currentIndex = 1;
  if (Number(job.progress_percent) >= 92) currentIndex = 2;
  if (job.status === "completed" || ["building", "ready"].includes(job.preview_status)) currentIndex = 3;
  const statusText = job.preview_status === "ready"
    ? "게임이 완성되었습니다. Preview에서 바로 플레이할 수 있습니다."
    : job.preview_status === "building"
      ? "완성된 게임을 WebGL Preview로 빌드하고 있습니다."
      : job.status === "failed"
        ? "게임 조립 또는 최종 검증에서 문제가 발생했습니다."
        : currentIndex === 2
          ? "게임이 요구사항을 만족하는지 최종 확인하고 있습니다."
          : currentIndex === 1
            ? "게임 화면과 필요한 에셋을 구성하고 있습니다."
            : "검증된 Feature를 하나의 게임으로 결합하고 있습니다.";
  gameAssemblyStatus.textContent = statusText;
  gameAssembly.classList.toggle("game-assembly--failed", job.status === "failed");
  gameAssemblySteps.querySelectorAll("li").forEach((item) => {
    const index = steps.indexOf(item.dataset.stage);
    item.className = index < currentIndex ? "is-complete" : index === currentIndex ? "is-current" : "";
  });
}

async function decide(action) {
  if (!currentJobId) return;
  let body = "{}";
  if (action === "reject") {
    const feedback = rejectFeedback.value.trim();
    if (!feedback) {
      rejectFeedback.focus();
      showToast("Feature를 어떻게 바꿀지 한마디를 입력하세요.", true);
      return;
    }
    body = JSON.stringify({ feedback });
    notifiedMilestones.delete(`${currentJobId}:feature`);
  }
  document.querySelector("#confirm-button").disabled = true;
  document.querySelector("#reject-button").disabled = true;
  try {
    const job = await api(`/api/jobs/${currentJobId}/${action}`, { method: "POST", body });
    if (action === "reject") rejectFeedback.value = "";
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
  updateAgentHarnessSettings();
  restoreNotificationSetting();
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
  await refreshCodexAuth();
}

imageStyle.addEventListener("change", updateCustomImageState);
gameBuilder.addEventListener("change", updateAgentHarnessSettings);
completionNotifications.addEventListener("change", () => {
  saveNotificationSetting();
  updateNotificationStatus();
  if (notificationSettingEnabled()) {
    void prepareCompletionNotifications({ requestPermission: true });
  }
});
modelSettingsToggle.addEventListener("click", () => {
  setModelSettingsExpanded(modelSettingsToggle.getAttribute("aria-expanded") !== "true");
});
copyLogButton.addEventListener("click", copyWorkflowLog);
codexLoginButton.addEventListener("click", startCodexDeviceLogin);
codexLogoutButton.addEventListener("click", logoutCodex);
workflowLog.addEventListener("keydown", (event) => {
  const selection = window.getSelection()?.toString() || "";
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c" && !selection) {
    event.preventDefault();
    copyWorkflowLog();
  }
});
featureList.addEventListener("click", (event) => {
  if (event.target.closest(".checklist-item")) return;
  const card = event.target.closest(".feature-card");
  if (card) toggleFeatureCard(card);
});
featureList.addEventListener("keydown", (event) => {
  const card = event.target.closest(".feature-card");
  if (!card || event.target !== card || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  toggleFeatureCard(card);
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
