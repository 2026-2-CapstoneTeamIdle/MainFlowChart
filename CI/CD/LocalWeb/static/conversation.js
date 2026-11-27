/* Project navigation reuses the existing generation workflow and API. */
(() => {
  const key = "mainflow.conversations.v1";
  const dialog = document.querySelector("#settings-dialog");
  const list = document.querySelector("#project-conversations");
  const title = document.querySelector("#conversation-title");
  let projects = [];
  try { projects = JSON.parse(localStorage.getItem(key) || "[]"); } catch { /* use an empty workspace */ }
  if (!Array.isArray(projects)) projects = [];
  projects = projects.filter(p => p && typeof p.id === "string" && typeof p.name === "string");
  let selected = null;
  let submitting = false;
  let renameInput = null;
  let pendingDeleteId = null;
  let pendingBottomJob = null;
  function scrollConversationToBottom(projectId) {
    // Wait for the workflow renderer and browser layout to finish after switching.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (selected !== projectId) return;
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" });
    }));
  }
  let listSignature = "";
  const projectStates = new Map();
  const activeProjectExports = new Map();
  const pendingRevisionRequests = new Set();
  const missingJobs = new Set();
  function isWorking(job) {
    return ["analyzing_features", "running", "cancelling"].includes(job?.status)
      || job?.revision_status === "running" || job?.preview_status === "building";
  }
  function observeProject(project, job) {
    if (!project.manuallyNamed && job.suggested_project_name && project.namedForJob !== job.job_id) {
      project.name = job.suggested_project_name;
      project.namedForJob = job.job_id;
      if (selected === project.id) title.textContent = project.name;
      persist();
    }
    projectStates.set(job.job_id, job);
    const notification = { ...job, conversation_name: project.name };
    observeJobNotifications(notification);
    void exportProject(project, job);
    renderList();
  }
  let backgroundPolling = false;
  async function pollOtherProjects() {
    if (backgroundPolling) return;
    backgroundPolling = true;
    try {
      await Promise.allSettled(projects.filter(project => {
        if (!project.jobId || project.jobId === currentJobId || missingJobs.has(project.jobId)) return false;
        const last = projectStates.get(project.jobId);
        return !last || isWorking(last) || !["completed", "failed", "cancelled"].includes(last.status);
      }).map(async project => {
        try {
          const response = await fetch(`/api/jobs/${encodeURIComponent(project.jobId)}?detail_features=`);
          if (response.status === 404) { missingJobs.add(project.jobId); return; }
          if (!response.ok) return;
          const job = await response.json();
          if (projects.includes(project) && project.jobId === job.job_id) observeProject(project, job);
        } catch { /* Retry transient network failures on the next poll. */ }
      }));
    } finally { backgroundPolling = false; }
  }
  const deleteDialog = document.querySelector("#delete-project-dialog");
  document.querySelector("#cancel-delete-project").addEventListener("click", () => deleteDialog.close());
  deleteDialog.addEventListener("close", () => { pendingDeleteId = null; });
  document.querySelector("#confirm-delete-project").addEventListener("click", () => {
    if (submitting || !pendingDeleteId) return;
    const id = pendingDeleteId;
    projects = projects.filter(p => p.id !== id);
    deleteDialog.close();
    if (selected === id) { selected = null; if (projects.length) select(projects[0].id); else create(); }
    persist(); renderList();
  });
  const persist = () => {
    try { localStorage.setItem(key, JSON.stringify(projects)); } catch { showToast("브라우저 저장 공간이 부족해 프로젝트 목록을 저장하지 못했습니다.", true); }
  };
  const requestPanel = requestForm.closest("section");
  const logPanel = workflowLog.closest("section");
  document.querySelector("#connection-settings").append(codexAuthPanel);
  codexAuthPanel.setAttribute("role", "tabpanel");
  codexAuthPanel.setAttribute("aria-labelledby", "codex-tab");
  document.querySelector("#ai-settings").append(document.querySelector("#models-heading").closest("section"));
  const openSettings = () => { if (!dialog.open) dialog.showModal(); };
  document.querySelector("#open-settings").addEventListener("click", openSettings);
  document.querySelector("#close-settings").addEventListener("click", () => dialog.close());
  for (const provider of ["codex", "claude"]) {
    document.querySelector(`#${provider}-tab`).addEventListener("click", () => {
      codexAuthPanel.hidden = provider !== "codex";
      document.querySelector("#claude-connection").hidden = provider !== "claude";
      for (const name of ["codex", "claude"]) document.querySelector(`#${name}-tab`).setAttribute("aria-selected", String(name === provider));
    });
  }
  const theme = document.querySelector("#dark-mode-toggle");
  try { theme.checked = localStorage.getItem("mainflow.darkMode") === "true"; } catch {}
  function applyTheme() {
    document.body.classList.toggle("dark-mode", theme.checked);
    try { localStorage.setItem("mainflow.darkMode", String(theme.checked)); } catch {}
  }
  theme.addEventListener("change", applyTheme);
  applyTheme();
  try { localStorage.removeItem("mainflow.sidebarCollapsed"); } catch {}
  const localFolders = new Map();
  const exports = new WeakMap();
  const folderStatus = document.querySelector("#local-folder-status");
  const outputInput = document.querySelector("#output-directory");
  document.querySelector("#choose-output-directory").addEventListener("click", async () => {
    if (!window.showDirectoryPicker) {
      showToast("폴더 선택은 localhost 또는 HTTPS의 Chrome·Edge에서 지원합니다.", true); return;
    }
    const id = selected;
    try {
      const handle = await window.showDirectoryPicker({ mode: "readwrite", id: "unity-project-output" });
      const project = projects.find(p => p.id === id);
      if (!project) return;
      localFolders.set(id, handle);
      project.localFolderName = handle.name;
      if (selected === id) {
        outputInput.value = handle.name;
        outputInput.dataset.localFolder = "true";
        folderStatus.textContent = "생성 완료 후 선택한 폴더 안에 Unity 프로젝트를 저장합니다. 이 페이지를 열어두세요.";
        saveDraft();
      }
      persist();
      const job = projectStates.get(project.jobId);
      if (job) void exportProject(project, job, true);
    } catch (error) { if (error.name !== "AbortError") showToast(`폴더 선택 실패: ${error.message}`, true); }
  });
  document.querySelector("#reset-output-directory").addEventListener("click", () => {
    localFolders.delete(selected);
    const project = projects.find(p => p.id === selected);
    if (project) delete project.localFolderName;
    outputInput.value = ""; delete outputInput.dataset.localFolder;
    folderStatus.textContent = "기본 저장 위치를 사용합니다."; saveDraft();
  });
  async function exportProject(project, job, retry = false) {
    const handle = localFolders.get(project.id);
    if (!handle || job.status !== "completed" || job.preview_status === "building" || job.revision_status === "running" || pendingRevisionRequests.has(job.job_id)) return;
    let history = exports.get(handle);
    if (!history) { history = new Map(); exports.set(handle, history); }
    const version = `${job.job_id}:${job.revision_messages?.length || 0}`;
    if (history.get(version) && !(retry && history.get(version) === "failed")) return;
    history.set(version, "saving");
    activeProjectExports.set(job.job_id, (activeProjectExports.get(job.job_id) || 0) + 1);
    refreshProjectComposer(job.job_id);
    const status = text => {
      if (selected === project.id && localFolders.get(project.id) === handle) folderStatus.textContent = text;
    };
    let snapshot = null;
    try {
      if (await handle.queryPermission({ mode: "readwrite" }) !== "granted") {
        throw new Error("폴더 선택 버튼을 다시 눌러 저장 권한을 허용하세요.");
      }
      status("Unity 프로젝트를 선택한 폴더에 저장하고 있습니다…");
      const manifest = await api(`/api/jobs/${job.job_id}/project-files`);
      snapshot = manifest.snapshot;
      if (!snapshot) throw new Error("내보내기용 프로젝트 ID를 받지 못했습니다.");
      const target = await handle.getDirectoryHandle(`Unity-${job.project_id}-${Date.now()}`, { create: true });
      for (const path of manifest.files) {
        const parts = path.split("/"); let directory = target;
        for (const part of parts.slice(0, -1)) directory = await directory.getDirectoryHandle(part, { create: true });
        const response = await fetch(`/api/jobs/${job.job_id}/project-file?path=${encodeURIComponent(path)}&snapshot=${encodeURIComponent(snapshot)}`);
        if (!response.ok) throw new Error(`파일 다운로드 실패: ${path}`);
        const file = await directory.getFileHandle(parts.at(-1), { create: true });
        const writable = await file.createWritable();
        try { await writable.write(await response.blob()); await writable.close(); }
        catch (error) { await writable.abort().catch(() => {}); throw error; }
      }
      history.set(version, "saved"); status(`${handle.name}/${target.name} 저장 완료`);
    } catch (error) {
      history.set(version, "failed"); status(`저장 실패: ${error.message} 폴더를 다시 선택하면 재시도합니다.`);
    } finally {
      if (snapshot) {
        try { await api(`/api/jobs/${job.job_id}/project-files/${encodeURIComponent(snapshot)}`, { method: "DELETE" }); }
        catch { /* Server cleanup can be retried without changing the export result. */ }
      }
      const remaining = activeProjectExports.get(job.job_id) - 1;
      if (remaining > 0) activeProjectExports.set(job.job_id, remaining);
      else activeProjectExports.delete(job.job_id);
      refreshProjectComposer(job.job_id);
    }
  }
  const messages = document.createElement("section");
  messages.className = "conversation-messages";
  messages.setAttribute("aria-live", "polite");
  logPanel.after(messages);
  const composer = document.querySelector("#project-message");
  const send = document.querySelector("#send-project-message");
  let chatJob = null;
  function refreshProjectComposer(jobId) {
    if (chatJob?.job_id === jobId && currentJobId === jobId) renderChat(chatJob);
  }
  function updateComposerButton(job) {
    const working = isWorking(job);
    send.classList.toggle("composer-stop", working);
    send.setAttribute("aria-label", working ? "개발 중지" : "메시지 보내기");
    send.title = working ? "진행 중인 작업 중지" : "메시지 보내기";
    send.innerHTML = working
      ? '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor" /></svg>'
      : '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /></svg>';
    send.disabled = working ? job.status === "cancelling" : composer.disabled;
  }
  function renderChat(job) {
    chatJob = job;
    const saving = activeProjectExports.has(job?.job_id);
    const requesting = pendingRevisionRequests.has(job?.job_id);
    const enabled = ["completed", "failed"].includes(job?.status) && Boolean(job?.project_id) && job.project_available !== false && job.preview_status !== "building"
      && job.revision_status !== "running" && !saving && !requesting && ["codex_cli", "claude_code"].includes(job.game_builder);
    composer.disabled = !enabled; send.disabled = !enabled;
    updateComposerButton(job);
    composer.placeholder = enabled ? job.status === "failed" ? "생성 오류 수정을 요청하세요. Enter 전송 · Shift+Enter 줄바꿈" : "추가 요청을 입력하세요. Enter 전송 · Shift+Enter 줄바꿈" : "수정할 Unity 프로젝트가 생성되면 추가 요청을 보낼 수 있습니다.";
    document.querySelector("#composer-help").textContent = saving ? "프로젝트를 폴더에 저장하고 있습니다. 저장이 끝나면 추가 요청을 보낼 수 있습니다."
      : requesting ? "수정 요청을 전송하고 있습니다…"
      : job?.revision_status === "running" ? "에이전트가 프로젝트를 수정하고 있습니다…" : "Enter 전송 · Shift+Enter 줄바꿈";
    messages.replaceChildren();
    const turns = job ? workflowLogTurns(job) : null;
    for (const [index, message] of (job?.revision_messages || []).entries()) {
      const bubble = document.createElement("article");
      bubble.className = `chat-message chat-message--${message.role}`;
      const heading = document.createElement("strong"); heading.textContent = message.role === "user" ? "나" : job.game_builder === "claude_code" ? "Claude Code" : "Codex";
      const content = document.createElement("p"); content.textContent = message.content;
      bubble.append(heading, content); messages.append(bubble);
      if (message.role === "user") {
        const section = document.createElement("section"); section.className = "conversation-activity revision-activity";
        section.setAttribute("aria-label", "추가 요청 작업 기록");
        const caption = document.createElement("div"); caption.className = "activity-caption"; caption.textContent = "추가 요청 작업 기록";
        const log = document.createElement("div"); log.className = "workflow-log";
        const key = `${job.job_id}:revision:${index}`;
        const lines = turns.revisions.get(index) || [];
        renderActivityRows(log, lines, key);
        const actions = document.createElement("div"); actions.className = "log-view-actions";
        const toggle = document.createElement("button"); toggle.type = "button"; toggle.className = "secondary-button compact-button";
        const copy = document.createElement("button"); copy.type = "button"; copy.className = "secondary-button compact-button"; copy.textContent = "전체 로그 복사";
        copy.addEventListener("click", () => void copyWorkflowLog(lines));
        const label = () => { toggle.textContent = compactLogJobs.has(key) ? "자세히 보기" : "간단히 보기"; toggle.setAttribute("aria-expanded", String(!compactLogJobs.has(key))); copy.hidden = compactLogJobs.has(key); };
        label();
        toggle.addEventListener("click", () => {
          const before = toggle.getBoundingClientRect().top;
          if (compactLogJobs.has(key)) compactLogJobs.delete(key); else compactLogJobs.add(key);
          renderActivityRows(log, lines, key); label();
          window.scrollBy({ top: toggle.getBoundingClientRect().top - before, behavior: "instant" });
        });
        actions.append(toggle, copy); section.append(caption, log, actions); messages.append(section);
      }
    }
  }
  async function sendMessage() {
    if (composer.disabled || !composer.value.trim() || !chatJob) return;
    const id = currentJobId;
    if (activeProjectExports.has(id) || pendingRevisionRequests.has(id)) return;
    const project = projects.find(project => project.jobId === id && project.id === selected);
    if (!project) return;
    const message = composer.value.trim();
    pendingRevisionRequests.add(id);
    composer.disabled = true; send.disabled = true;
    try {
      const job = await api(`/api/jobs/${id}/messages`, { method: "POST", body: JSON.stringify({ message }) });
      if (!projects.includes(project) || project.jobId !== id) return;
      observeProject(project, job);
      if (id !== currentJobId) return;
      lastAppliedPollSequence = ++pollRequestSequence;
      composer.value = ""; renderJob(job); startPolling();
    } catch (error) { if (id === currentJobId) showToast(error.message, true); }
    finally {
      pendingRevisionRequests.delete(id);
      refreshProjectComposer(id);
      if (projects.includes(project) && project.jobId === id) {
        const latest = projectStates.get(id);
        if (latest) void exportProject(project, latest);
      }
    }
  }
  send.addEventListener("click", async () => {
    if (!isWorking(chatJob)) { void sendMessage(); return; }
    const id = currentJobId;
    send.disabled = true;
    await stopJob();
    if (id === currentJobId) updateComposerButton(currentJob);
  });
  window.addEventListener("mainflow:job-unavailable", () => {
    if (chatJob) projectStates.set(chatJob.job_id, { ...chatJob, status: "failed", revision_status: "failed", preview_status: "failed" });
    renderChat(null); renderList();
  });
  composer.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); void sendMessage(); }
  });
  const defaults = Object.fromEntries(new FormData(requestForm));
  function saveDraft() {
    const project = projects.find(p => p.id === selected);
    if (!project) return;
    project.draft = Object.fromEntries(new FormData(requestForm));
    delete project.draft.custom_image;
    persist();
  }
  function renderList() {
    // Polling must not replace the input while the user is typing a project name.
    if (renameInput?.isConnected) return;
    const signature = JSON.stringify([selected, submitting, projects.map(p => [p.id, p.name, isWorking(projectStates.get(p.jobId))])]);
    if (signature === listSignature) return;
    listSignature = signature;
    list.replaceChildren();
    for (const project of projects) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = project.name;
      button.setAttribute("aria-current", project.id === selected ? "page" : "false");
      button.addEventListener("click", () => select(project.id));
      const row = document.createElement("div"); row.className = "project-row";
      row.classList.toggle("selected", project.id === selected);
      const working = isWorking(projectStates.get(project.jobId));
      row.classList.toggle("project-row--working", working);
      row.setAttribute("aria-label", `${project.name}${working ? " · 개발 중" : ""}`);
      if (working) {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.classList.add("project-progress-border");
        svg.setAttribute("aria-hidden", "true");
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", "1"); rect.setAttribute("y", "1");
        rect.setAttribute("width", "calc(100% - 2px)"); rect.setAttribute("height", "calc(100% - 2px)");
        rect.setAttribute("rx", "3");
        svg.append(rect); row.append(svg);
      }
      row.addEventListener("click", event => {
        if (event.target.closest("button, input")) return;
        select(project.id);
      });
      const rename = document.createElement("button"); rename.type = "button"; rename.textContent = "✎"; rename.setAttribute("aria-label", `${project.name} 이름 수정`);
      rename.addEventListener("click", () => {
        if (submitting) return;
        const input = document.createElement("input");
        input.className = "project-name-input";
        input.value = project.name; input.maxLength = 100;
        input.setAttribute("aria-label", "프로젝트 이름");
        let finished = false;
        function finish(save) {
          if (finished) return;
          finished = true; renameInput = null; listSignature = "";
          if (save && input.value.trim()) {
            project.name = input.value.trim(); project.manuallyNamed = true;
            persist();
            if (selected === project.id) title.textContent = project.name;
          }
          renderList();
        }
        input.addEventListener("keydown", event => {
          if (event.isComposing) return;
          if (event.key === "Enter") { event.preventDefault(); finish(true); }
          if (event.key === "Escape") { event.preventDefault(); finish(false); }
        });
        input.addEventListener("blur", () => finish(true));
        button.replaceWith(input); renameInput = input;
        input.focus(); input.select();
      });
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×"; remove.setAttribute("aria-label", `${project.name} 삭제`);
      remove.addEventListener("click", () => {
        if (submitting) return;
        pendingDeleteId = project.id;
        document.querySelector("#delete-project-name").textContent = project.name;
        deleteDialog.showModal();
      });
      row.prepend(button, rename, remove); list.append(row);
    }
  }
  function select(id, scrollToBottom = true) {
    if (submitting) return;
    saveDraft();
    selected = id;
    const project = projects.find(p => p.id === id);
    window.clearInterval(pollTimer);
    window.clearTimeout(featureMergeTimer);
    currentJobId = project.jobId || null;
    pendingBottomJob = scrollToBottom ? currentJobId : null;
    currentJob = null;
    renderChat(null);
    expandedFeatureIds = new Set(); openedCriteriaByFeature = new Map(); checklistScrollByFeature = new Map();
    lastFeatureRenderKey = null; featureViewMode = "cards";
    title.textContent = project.name;
    requestForm.reset();
    for (const [name, value] of Object.entries(project.draft || defaults)) {
      const control = requestForm.elements.namedItem(name);
      if (!control || control.type === "file") continue;
      if (control.type === "checkbox") control.checked = Boolean(value);
      else control.value = value;
    }
    outputInput.dataset.localFolder = "true";
    outputInput.value = project.localFolderName || "";
    folderStatus.textContent = project.localFolderName
      ? localFolders.has(project.id) ? `선택한 폴더: ${project.localFolderName}` : `${project.localFolderName} — 페이지가 새로 열렸으므로 폴더를 다시 선택하세요.`
      : "기본 저장 위치를 사용합니다.";
    updateAgentHarnessSettings({ restore: project.draft || {} }); updateCustomImageState();
    featurePanel.classList.add("is-hidden");
    logPanel.hidden = !currentJobId;
    workflowLog.textContent = "프로젝트 실행 정보를 불러오는 중입니다...";
    phaseBadge.textContent = currentJobId ? "불러오는 중" : "입력 대기";
    setRunButtons(Boolean(currentJobId));
    stopButton.classList.add("is-hidden");
    openUnityButton.classList.add("is-hidden"); previewButton.classList.add("is-hidden");
    document.querySelector("#project-tools").hidden = true;
    document.querySelector("#composer-workflow-bar").hidden = true;
    renderList();
    const cachedJob = projectStates.get(currentJobId);
    if (cachedJob) renderJob(cachedJob);
    if (scrollToBottom) scrollConversationToBottom(id);
    if (currentJobId) startPolling();
  }
  function create() {
    if (submitting) return;
    const project = { id: crypto.randomUUID(), name: `새 프로젝트 ${projects.length + 1}`, draft: {} };
    projects.push(project); select(project.id, false); persist();
    requestPanel.scrollIntoView({ block: "start", behavior: "smooth" });
  }
  document.querySelector("#new-conversation").addEventListener("click", create);
  requestForm.addEventListener("change", saveDraft);
  window.addEventListener("mainflow:job", event => {
    const project = projects.find(p => p.id === selected);
    if (!project) return;
    const job = event.detail;
    if (pendingBottomJob === job.job_id) {
      pendingBottomJob = null;
      scrollConversationToBottom(project.id);
    }
    void exportProject(project, job);
    renderChat(job);
    project.jobId = job.job_id;
    observeProject(project, job);
    title.textContent = project.name;
    logPanel.hidden = false;
    saveDraft(); renderList();
  });
  window.addEventListener("mainflow:settings", openSettings);
  window.addEventListener("mainflow:job-update", event => {
    const job = event.detail;
    const project = projects.find(project => project.jobId === job.job_id);
    if (project) observeProject(project, job);
  });
  window.addEventListener("mainflow:submitting", event => {
    submitting = event.detail;
    document.querySelector("#new-conversation").disabled = submitting;
    for (const button of list.querySelectorAll("button")) button.disabled = submitting;
  });
  if (projects.length) select(projects[projects.length - 1].id); else create();
  window.setInterval(pollOtherProjects, 3000);
  void pollOtherProjects();
  try {
    if (!localStorage.getItem("mainflow.setupSeen")) {
      openSettings(); localStorage.setItem("mainflow.setupSeen", "true");
    }
  } catch { openSettings(); }
})();
