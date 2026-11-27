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
const notificationHistoryKey = "mainflow.notifiedMilestones.v1";
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
let notifiedMilestones = loadNotificationHistory();
const observedNotificationStates = new Map();
let toastTimer = null;
let codexAuthPollTimer = null;
let codexAuthenticated = false;
let expandedFeatureIds = new Set();
let openedCriteriaByFeature = new Map();
let checklistScrollByFeature = new Map();
let lastFeatureRenderKey = null;
let pollRequestSequence = 0;
let lastAppliedPollSequence = 0;
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

function updateAgentHarnessSettings(options = {}) {
  const restored = options.restore;
  if (!restored && activeAgentBuilder && agentHarnessCatalog[activeAgentBuilder]) {
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
  const saved = restored
    ? { model: restored.agent_model, effort: restored.agent_reasoning_effort }
    : agentHarnessSelections[builder] || {};
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

function loadNotificationHistory() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(notificationHistoryKey) || "[]");
    return new Set(Array.isArray(saved) ? saved.filter(key => typeof key === "string") : []);
  } catch { return new Set(); }
}

function notificationMilestoneKey(job, milestone) {
  return `${job.job_id || currentJobId}:${milestone}:${milestone === "feature" ? job.feature_revision || 0 : milestone === "revision" ? job.revision_messages?.length || 0 : ""}`;
}

function rememberNotificationMilestone(key) {
  notifiedMilestones.add(key);
  try {
    window.localStorage.setItem(notificationHistoryKey, JSON.stringify([...notifiedMilestones].slice(-2000)));
  } catch { /* In-memory deduplication still works when browser storage is unavailable. */ }
}

function rememberJobMilestones(job) {
  // Restored results are history, not new completion events.
  if (job.status === "awaiting_confirmation") rememberNotificationMilestone(notificationMilestoneKey(job, "feature"));
  if (["completed", "failed", "cancelled"].includes(job.status)) rememberNotificationMilestone(notificationMilestoneKey(job, "terminal"));
  if (["completed", "failed"].includes(job.revision_status)) rememberNotificationMilestone(notificationMilestoneKey(job, "revision"));
}

function observeJobNotifications(job) {
  const id = job.job_id;
  if (!id) return;
  const previous = observedNotificationStates.get(id);
  observedNotificationStates.set(id, {
    status: job.status,
    revision_status: job.revision_status,
    feature_revision: job.feature_revision || 0,
  });
  // The first snapshot on every page load is a baseline, even if storage is unavailable.
  // Only a later observed transition can trigger sound or a system notification.
  if (!previous) {
    rememberJobMilestones(job);
    return;
  }
  if (job.status === "awaiting_confirmation" && previous.status === "analyzing_features") {
    notifyJobMilestone(job, "feature");
  }
  if (["completed", "failed", "cancelled"].includes(job.status)
      && ["analyzing_features", "awaiting_confirmation", "running", "cancelling"].includes(previous.status)) {
    notifyJobMilestone(job, "terminal");
  }
  if (["completed", "failed"].includes(job.revision_status) && previous.revision_status === "running") {
    notifyJobMilestone(job, "revision");
  }
}

function notifyJobMilestone(job, milestone) {
  const key = notificationMilestoneKey(job, milestone);
  if (notifiedMilestones.has(key)) return;
  rememberNotificationMilestone(key);
  if (!notificationSettingEnabled()) return;
  if (milestone === "revision") {
    const succeeded = job.revision_status === "completed";
    void playNotificationTone(succeeded ? "success" : "failure");
    void showSystemNotification(
      succeeded ? "겜만툴 · 게임 수정 완료" : "겜만툴 · 게임 수정 실패",
      `${job.conversation_name || job.project_id || "프로젝트"} · ${succeeded ? "추가 요청 처리가 완료되었습니다." : "추가 요청 처리에 실패했습니다. 대화를 확인하세요."}`,
      key,
    );
    return;
  }
  if (milestone === "feature") {
    void playNotificationTone("feature");
    void showSystemNotification(
      "겜만툴 · Feature 분석 완료",
      `${job.conversation_name || job.project_id || "프로젝트"} · ${job.features.length}개 Feature를 확인하고 Confirm 또는 Reject를 선택하세요.`,
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

async function copyWorkflowLog(logs = null) {
  const text = Array.isArray(logs) ? logs.join("\n") : currentJob?.logs?.join("\n") || workflowLog.textContent || "";
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
    window.dispatchEvent(new Event("mainflow:settings"));
    codexAuthPanel.scrollIntoView({ behavior: "smooth", block: "center" });
    showToast("Codex CLI를 선택하려면 먼저 Docker 내부 Codex에 로그인하세요.", true);
    return;
  }
  setRunButtons(true);
  window.dispatchEvent(new CustomEvent("mainflow:submitting", { detail: true }));
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
      output_directory: document.querySelector("#output-directory").dataset.localFolder === "true" ? null : form.get("output_directory")?.trim() || null,
      custom_image: await fileToPayload(customImage.files[0]),
    };
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    currentJobId = job.job_id;
    expandedFeatureIds = new Set();
    openedCriteriaByFeature = new Map();
    checklistScrollByFeature = new Map();
    lastFeatureRenderKey = null;
    pollRequestSequence = 0;
    lastAppliedPollSequence = 0;
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
  } finally {
    window.dispatchEvent(new CustomEvent("mainflow:submitting", { detail: false }));
  }
}

function startPolling() {
  window.clearInterval(pollTimer);
  pollTimer = window.setInterval(refreshJob, 1000);
  refreshJob();
}

async function refreshJob() {
  if (!currentJobId) return;
  const requestedJobId = currentJobId;
  const requestedFeatureIds = [...expandedFeatureIds].sort().join(",");
  const sequence = ++pollRequestSequence;
  try {
    const details = encodeURIComponent(requestedFeatureIds);
    const job = await api(`/api/jobs/${requestedJobId}?detail_features=${details}`);
    if (requestedJobId !== currentJobId
        || requestedFeatureIds !== [...expandedFeatureIds].sort().join(",")
        || sequence < lastAppliedPollSequence) return;
    lastAppliedPollSequence = sequence;
    renderJob(job);
    const previewFinished = ["ready", "failed", "cancelled", "unavailable"].includes(job.preview_status);
    if (job.revision_status === "running") return;
    if (job.status === "cancelled"
        || (job.status === "failed" && job.preview_status !== "building")
        || (job.status === "completed" && previewFinished)) {
      window.clearInterval(pollTimer);
    }
  } catch (error) {
    if (requestedJobId !== currentJobId
        || requestedFeatureIds !== [...expandedFeatureIds].sort().join(",")
        || sequence < lastAppliedPollSequence) return;
    window.clearInterval(pollTimer);
    setRunButtons(false);
    stopButton.classList.add("is-hidden");
    phaseBadge.textContent = "다시 생성 가능";
    jobState.textContent = "이전 작업 연결 종료";
    if (!currentJob || currentJob.job_id !== requestedJobId) {
      workflowLog.textContent = "이전 작업 정보를 불러오지 못했습니다. 서버가 재시작되었거나 작업 파일이 없을 수 있습니다. 위의 Generate 버튼으로 다시 생성할 수 있습니다.";
    }
    window.dispatchEvent(new Event("mainflow:job-unavailable"));
    showToast(error.message, true);
  }
}

const compactLogJobs = new Set();

function importantWorkflowLogs(logs) {
  return logs.filter(line => /^\[(?:WEB(?:GL)?|FLOW|RESULT|CHAT)\]/.test(line)
    || /^\[AGENT\]\[repair\]/.test(line)
    || /error|exception|failed|failure|실패|오류|중단/i.test(line));
}

function latestWorkflowDescription(logs) {
  const meaningful = logs.filter(line => /^\[(?:WEB(?:GL)?|FLOW|RESULT|CHAT|AGENT)\]/.test(line));
  const line = meaningful.at(-1) || logs.filter(line => line.trim()).at(-1) || "작업 기록을 기다리고 있습니다…";
  const description = line.replace(/^(?:\[[^\]]+\])+\s*/, "").replace(/\s+/g, " ").trim();
  return description.length > 100 ? `${description.slice(0, 100)}…` : description;
}

function workflowLogTurns(job) {
  const logs = job.logs || [];
  const users = (job.revision_messages || []).map((message, index) => ({ message, index }))
    .filter(item => item.message.role === "user");
  const legacyStarts = logs.map((line, index) => line.startsWith("[CHAT] 기존 Unity 프로젝트 추가 요청") ? index : -1).filter(index => index >= 0);
  const starts = users.map((item, index) => Number.isInteger(item.message.log_start)
    ? Math.max(0, Math.min(logs.length, item.message.log_start - (job.log_offset || 0)))
    : legacyStarts[index] ?? logs.length);
  return { initial: logs.slice(0, starts[0] ?? logs.length),
    revisions: new Map(users.map((item, index) => [item.index, logs.slice(starts[index], starts[index + 1] ?? logs.length)])) };
}

function groupWorkflowLogs(logs) {
  const stages = new Map();
  let stage = "기능 분석 및 검토";
  for (const line of logs) {
    const body = line.replace(/^(?:\[[^\]]+\])+\s*/, "");
    if (/^\[RESULT\]/.test(line)) stage = "실행 결과";
    else if (/^\[WEBGL\]/.test(line)) stage = "WebGL Preview 빌드";
    else if (/^\[CHAT\]/.test(line)) stage = "추가 요청 수정";
    else if (/^\[AGENT\]\[repair\]/.test(line)) stage = "Unity 검증 및 오류 수리";
    else if (/^\[(?:FLOW|WEB)\]/.test(line)) {
      if (/^(?:작업 .*Feature 분석|사용자 Condition|명시된 기능|Feature 구성을 거절)/.test(body)) stage = "기능 분석 및 검토";
      else if (/^(?:승인된 Feature별 Checklist|Feature Checklist|모든 Feature Checklist)/.test(body)) stage = "체크리스트 작성";
      else if (/^(?:게임 로직을 설계|이번 실행의 콘텐츠|설치된 .*(?:CLI|Code)|레벨에 배치된|HUD 패널)/.test(body)) stage = "게임 설계 및 구현";
      else if (/^(?:Unity 컴파일|실행 검증에서|진단용 Unity|요청 기능 생성은)/.test(body)) stage = "Unity 검증 및 오류 수리";
      else if (/^(?:이미지 에셋을 생성|사운드 에셋|게임 검증 결과를 바탕|유저 입력 \+|이미지 검증|사운드 검증)/.test(body)) stage = "이미지·사운드 생성 및 검증";
      else if (/^(?:검증을 통과한 .*에셋|컴파일을 통과한 진단용|실제 이미지 백엔드|목표 화면과)/.test(body)) stage = "에셋 적용 및 화면 확인";
      else if (/^(?:최종 에셋과|독립 Validator|독립 품질 평가|게임 생성 파이프라인이 완료)/.test(body)) stage = "최종 검증 및 품질 평가";
      else if (/^\[WEB\]\[ERROR\]/.test(line)) stage = "실행 결과";
    }
    if (!stages.has(stage)) stages.set(stage, { title: stage, logs: [] });
    stages.get(stage).logs.push(line);
  }
  return [...stages.values()];
}

const expandedLogRows = new Set();
function renderActivityRows(container, logs, key) {
  container.replaceChildren();
  if (compactLogJobs.has(key)) {
    const row = document.createElement("div"); row.className = "activity-latest";
    const icon = document.createElement("span"); icon.className = "activity-icon"; icon.textContent = "›";
    const text = document.createElement("span"); text.className = "activity-text";
    text.textContent = latestWorkflowDescription(logs); text.title = text.textContent;
    row.append(icon, text); container.append(row); return;
  }
  const visible = logs;
  if (!visible.length) { container.textContent = "작업 기록을 기다리고 있습니다…"; return; }
  groupWorkflowLogs(visible).forEach(group => {
    const row = document.createElement("details"); row.className = "activity-row";
    const id = `${key}:stage:${group.title}`;
    row.open = expandedLogRows.has(id);
    const summary = document.createElement("summary");
    const icon = document.createElement("span"); icon.className = "activity-icon"; icon.textContent = "›";
    const text = document.createElement("span"); text.className = "activity-text";
    text.textContent = group.title;
    const count = document.createElement("span"); count.className = "activity-count"; count.textContent = `${group.logs.length}개 기록`;
    summary.title = latestWorkflowDescription(group.logs);
    const detail = document.createElement("pre"); detail.className = "activity-raw"; detail.textContent = group.logs.join("\n");
    summary.append(icon, text, count); row.append(summary, detail);
    row.addEventListener("toggle", () => {
      if (!row.isConnected) return;
      if (row.open) expandedLogRows.add(id); else expandedLogRows.delete(id);
    });
    container.append(row);
  });
}

function renderWorkflowLog(job) {
  const compact = compactLogJobs.has(job.job_id);
  renderActivityRows(workflowLog, workflowLogTurns(job).initial, job.job_id);
  const toggle = document.querySelector("#toggle-log-view");
  toggle.textContent = compact ? "자세히 보기" : "간단히 보기";
  toggle.setAttribute("aria-expanded", String(!compact));
  copyLogButton.hidden = compact;
}

document.querySelector("#toggle-log-view").addEventListener("click", () => {
  if (!currentJob) return;
  const toggle = document.querySelector("#toggle-log-view");
  const before = toggle.getBoundingClientRect().top;
  if (compactLogJobs.has(currentJob.job_id)) compactLogJobs.delete(currentJob.job_id);
  else compactLogJobs.add(currentJob.job_id);
  renderWorkflowLog(currentJob);
  window.scrollBy({ top: toggle.getBoundingClientRect().top - before, behavior: "instant" });
});

const focusedFeatureReviews = new Set();

function renderJob(job) {
  if (job.job_id !== currentJobId) return;
  const reviewKey = `${job.job_id}:${job.feature_revision || 0}`;
  const needsReviewFocus = job.status === "awaiting_confirmation" && job.features?.length
    && !focusedFeatureReviews.has(reviewKey);
  const followLatest = document.documentElement.scrollHeight - window.scrollY - window.innerHeight < 160;
  currentJob = job;
  window.dispatchEvent(new CustomEvent("mainflow:job", { detail: job }));
  observeJobNotifications(job);
  const stateLabels = {
    analyzing_features: "Feature 분석 중", awaiting_confirmation: "사용자 승인 대기",
    running: "게임 생성 중", cancelling: "중단 중", cancelled: "취소됨",
    completed: "완료", failed: "실패",
  };
  const label = stateLabels[job.status] || job.status;
  jobState.textContent = label;
  phaseBadge.textContent = label;
  renderWorkflowLog(job);
  renderProgress(job);
  if (job.features?.length) {
    renderFeatureWorkspace(job);
    featurePanel.classList.remove("is-hidden");
  } else {
    featurePanel.classList.add("is-hidden");
  }
  const previewBuilding = job.preview_status === "building";
  const active = ["analyzing_features", "awaiting_confirmation", "running", "cancelling"].includes(job.status) || previewBuilding || job.revision_status === "running";
  setRunButtons(active);
  stopButton.classList.add("is-hidden");
  stopButton.disabled = job.status === "cancelling";
  document.querySelector("#confirm-button").disabled = job.status !== "awaiting_confirmation";
  document.querySelector("#reject-button").disabled = job.status !== "awaiting_confirmation";
  rejectFeedback.disabled = job.status !== "awaiting_confirmation";
  const canOpenUnity = ["completed", "failed"].includes(job.status) && Boolean(job.project_id) && !previewBuilding;
  openUnityButton.classList.toggle("is-hidden", !["completed", "failed"].includes(job.status) || !job.project_id);
  openUnityButton.disabled = !canOpenUnity;
  renderPreviewButton(job);
  document.querySelector("#composer-workflow-bar").hidden = false;
  document.querySelector("#project-tools").hidden = !["completed", "failed"].includes(job.status) || !job.project_id;
  openUnityButton.disabled = !canOpenUnity || job.revision_status === "running";
  if (needsReviewFocus) requestAnimationFrame(() => requestAnimationFrame(() => {
    if (currentJobId !== job.job_id || currentJob?.status !== "awaiting_confirmation"
        || (currentJob.feature_revision || 0) !== (job.feature_revision || 0)
        || focusedFeatureReviews.has(reviewKey)) return;
    focusedFeatureReviews.add(reviewKey);
    featurePanel.scrollIntoView({ block: "start", behavior: "instant" });
  }));
  if (followLatest && !needsReviewFocus) requestAnimationFrame(() => {
    if (currentJobId === job.job_id) window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" });
  });
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
  previewButton.disabled = !canPreview || job.preview_status === "building" || job.revision_status === "running";
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
  const requestedJobId = currentJobId;
  stopButton.disabled = true;
  try {
    const job = await api(`/api/jobs/${requestedJobId}/cancel`, { method: "POST", body: "{}" });
    if (requestedJobId !== currentJobId) return;
    renderJob(job);
    window.clearInterval(pollTimer);
    showToast("작업을 중단했습니다.");
  } catch (error) {
    if (requestedJobId !== currentJobId) return;
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
  const requestedJobId = currentJobId;
  if (currentJob.preview_status === "ready" && currentJob.preview_url) {
    window.open(currentJob.preview_url, "_blank", "noopener,noreferrer");
    return;
  }
  previewButton.disabled = true;
  try {
    const job = await api(`/api/jobs/${requestedJobId}/build-webgl`, { method: "POST", body: "{}" });
    window.dispatchEvent(new CustomEvent("mainflow:job-update", { detail: job }));
    if (requestedJobId !== currentJobId) return;
    lastAppliedPollSequence = ++pollRequestSequence;
    renderJob(job);
    startPolling();
    showToast("WebGL Preview 빌드를 시작했습니다.");
  } catch (error) {
    if (requestedJobId !== currentJobId) return;
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
  const previousCards = new Map([...featureList.children].map((card) => [card.dataset.featureId, card]));
  const listScrollTop = featureList.scrollTop;
  const visibleCard = [...featureList.children].find((card) => {
    const bounds = card.getBoundingClientRect();
    return bounds.bottom > 0 && bounds.top < window.innerHeight;
  });
  const anchorId = visibleCard?.dataset.featureId;
  const anchorTop = visibleCard?.getBoundingClientRect().top;
  features.forEach((feature, index) => {
    const featureId = String(feature.feature_id || "feature");
    const status = feature.status || "pending";
    const expanded = expandedFeatureIds.has(featureId);
    const cardRenderKey = JSON.stringify([feature, expanded]);
    const previousCard = previousCards.get(featureId);
    previousCards.delete(featureId);
    if (previousCard?._featureRenderKey === cardRenderKey) {
      if (featureList.children[index] !== previousCard) {
        featureList.insertBefore(previousCard, featureList.children[index] || null);
      }
      return;
    }
    const previousCriteria = previousCard?.querySelectorAll(".checklist-item details");
    if (previousCriteria?.length) {
      openedCriteriaByFeature.set(featureId, new Set(
        [...previousCriteria].filter((details) => details.open).map(
          (details) => details.closest(".checklist-item")?.dataset.criterionId,
        ).filter(Boolean),
      ));
      checklistScrollByFeature.set(
        featureId,
        previousCard.querySelector(".feature-checklist ol")?.scrollTop || 0,
      );
    }
    const openCriteria = openedCriteriaByFeature.get(featureId) || new Set();
    const checklistScrollTop = checklistScrollByFeature.get(featureId) || 0;
    const checklist = Array.isArray(feature.checklist) ? feature.checklist : [];
    const checklistItems = checklist.length
      ? checklist.map((criterion) => renderChecklistCriterion(criterion)).join("")
      : `<p class="feature-checklist__empty">${checklistEmptyLabel(feature.checklist_status)}</p>`;
    const item = document.createElement("article");
    item.className = `feature-card feature-card--${escapeHtml(status)}`;
    item.dataset.featureId = featureId;
    item.dataset.checklistCount = String(feature.checklist_count || 0);
    item._featureRenderKey = cardRenderKey;
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
          <span>${escapeHtml(feature.checklist_count || 0)}개</span>
        </div>
        <ol>${checklistItems}</ol>
      </div>`;
    if (previousCard) previousCard.replaceWith(item);
    else featureList.insertBefore(item, featureList.children[index] || null);
    if (featureList.children[index] !== item) {
      featureList.insertBefore(item, featureList.children[index] || null);
    }
    item.querySelectorAll(".checklist-item").forEach((criterion) => {
      if (openCriteria.has(criterion.dataset.criterionId)) {
        criterion.querySelector("details").open = true;
      }
    });
    item.querySelector(".feature-checklist ol").scrollTop = checklistScrollTop;
  });
  previousCards.forEach((card) => card.remove());
  featureList.scrollTop = listScrollTop;
  const currentAnchor = [...featureList.children].find((card) => card.dataset.featureId === anchorId);
  if (currentAnchor && anchorTop !== undefined) {
    window.scrollBy(0, currentAnchor.getBoundingClientRect().top - anchorTop);
  }
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
    ? "Feature에 맞는 10~30개 검증 항목을 작성하고 있습니다."
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
    openedCriteriaByFeature.clear();
    checklistScrollByFeature.clear();
  }
  document.querySelector("#confirm-button").disabled = true;
  document.querySelector("#reject-button").disabled = true;
  try {
    const job = await api(`/api/jobs/${currentJobId}/${action}`, { method: "POST", body });
    if (action === "reject") rejectFeedback.value = "";
    lastAppliedPollSequence = ++pollRequestSequence;
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
