const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/conversation.js"), "utf8");

test("revision response follows its original project after switching, including background completion", async () => {
  const original = { id: "P-A", jobId: "A", name: "Original", manuallyNamed: true };
  const job = { job_id: "A", status: "completed", revision_status: "idle" };
  let resolveRequest;
  const request = new Promise(resolve => { resolveRequest = resolve; });
  const observed = [];
  let renders = 0, polls = 0;
  const context = {
    projects: [original, { id: "P-B", jobId: "B", name: "Other" }], selected: "P-A", currentJobId: "A",
    composer: { disabled: false, value: "change" }, send: {}, chatJob: job,
    projectStates: new Map([["A", job]]), missingJobs: new Set(),
    activeProjectExports: new Map(), pendingRevisionRequests: new Set(), refreshProjectComposer() {},
    api: () => request, observeJobNotifications: snapshot => observed.push(snapshot),
    exportProject() {}, renderList() {}, persist() {},
    renderJob() { renders++; }, startPolling() { throw Error("must not poll the wrong selected project"); },
    renderChat() {}, showToast() {},
    fetch: async () => { polls++; return { ok: true, json: async () => ({ ...job, revision_status: "completed" }) }; },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("  function isWorking("), source.indexOf("  const deleteDialog")), context);
  vm.runInContext(source.slice(source.indexOf("  async function sendMessage("), source.indexOf("  send.addEventListener(")), context);
  const pending = context.sendMessage();
  context.selected = "P-B"; context.currentJobId = "B"; context.composer.value = "other draft";
  resolveRequest({ ...job, revision_status: "running" });
  await pending;
  assert.equal(context.projectStates.get("A").revision_status, "running");
  assert.equal(context.composer.value, "other draft");
  assert.equal(renders, 0);
  await context.pollOtherProjects();
  assert.equal(polls, 1);
  assert.equal(context.projectStates.get("A").revision_status, "completed");
  assert.deepEqual(observed.map(job => [job.conversation_name, job.revision_status]), [
    ["Original", "running"], ["Original", "completed"],
  ]);
});

function exportContext() {
  const requests = [];
  const context = {
    localFolders: new Map(), exports: new WeakMap(), selected: "P", folderStatus: {},
    activeProjectExports: new Map(), pendingRevisionRequests: new Set(), refreshProjectComposer() {},
    requests,
    api: async (url, options) => { requests.push([url, options?.method]); return options?.method === "DELETE" ? null : ({ files: ["file.txt"], snapshot: "a".repeat(32) }); },
    fetch: async url => { requests.push([url, "GET"]); return { ok: true, blob: async () => "project contents" }; },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("  async function exportProject("), source.indexOf("  const messages =")), context);
  return context;
}

function folder(name, permission = async () => "granted") {
  const writes = [];
  return {
    name, writes, queryPermission: permission,
    async getDirectoryHandle(targetName) {
      return { name: targetName, async getFileHandle(file) {
        return { async createWritable() { return {
          async write(contents) { writes.push([file, contents]); }, async close() {}, async abort() {},
        }; } };
      } };
    },
  };
}

const completed = { job_id: "J", project_id: "game", status: "completed", revision_messages: [] };

test("a successful revision saves a game recovered from initial generation failure", async () => {
  const context = exportContext();
  const destination = folder("recovered");
  context.localFolders.set("P", destination);
  await context.exportProject({ id: "P" }, {
    ...completed, status: "failed", revision_status: "completed",
    revision_messages: [{ role: "user" }, { role: "assistant" }],
  });
  assert.deepEqual(destination.writes, [["file.txt", "project contents"]]);
});

test("failed and cancelled revisions never save partially modified projects", async () => {
  const context = exportContext();
  const destination = folder("unverified");
  context.localFolders.set("P", destination);
  for (const revision_status of ["running", "failed", "cancelled"]) {
    await context.exportProject({ id: "P" }, {
      ...completed, revision_status, revision_messages: [{ role: "user" }],
    });
  }
  assert.deepEqual(destination.writes, []);
  assert.deepEqual(context.requests, []);
});

test("selecting a new folder saves an already exported version there and avoids duplicate polling copies", async () => {
  const context = exportContext();
  const first = folder("first"), second = folder("second");
  context.localFolders.set("P", first);
  await context.exportProject({ id: "P" }, completed);
  context.localFolders.set("P", second);
  await context.exportProject({ id: "P" }, completed, true);
  await context.exportProject({ id: "P" }, completed);
  assert.deepEqual(first.writes, [["file.txt", "project contents"]]);
  assert.deepEqual(second.writes, [["file.txt", "project contents"]]);
  assert.match(context.folderStatus.textContent, /^second\//);
  assert.ok(context.requests.some(([url]) => url.includes(`snapshot=${"a".repeat(32)}`)));
  assert.equal(context.requests.filter(([, method]) => method === "DELETE").length, 2);
});

test("an older folder export finishing late cannot overwrite the selected folder's status", async () => {
  const context = exportContext();
  let permit;
  const first = folder("first", () => new Promise(resolve => { permit = resolve; }));
  const second = folder("second");
  context.localFolders.set("P", first);
  const pending = context.exportProject({ id: "P" }, completed);
  context.localFolders.set("P", second);
  await context.exportProject({ id: "P" }, completed, true);
  permit("granted"); await pending;
  assert.match(context.folderStatus.textContent, /^second\//);
  assert.equal(first.writes.length, 1);
  assert.equal(second.writes.length, 1);
});

test("saving a project blocks revision requests until all folder exports have finished", async () => {
  const context = exportContext();
  let permit;
  const destination = folder("pending", () => new Promise(resolve => { permit = resolve; }));
  context.localFolders.set("P", destination);
  context.projects = [{ id: "P", jobId: "J" }]; context.currentJobId = "J";
  context.composer = { disabled: false, value: "change" }; context.send = {}; context.chatJob = completed;
  vm.runInContext(source.slice(source.indexOf("  async function sendMessage("), source.indexOf("  send.addEventListener(")), context);
  const saving = context.exportProject(context.projects[0], completed);
  assert.equal(context.activeProjectExports.get("J"), 1);
  let revisionCalls = 0;
  context.api = async () => { revisionCalls++; return completed; };
  await context.sendMessage();
  assert.equal(revisionCalls, 0, "revision POST must not interrupt a file export");
  context.api = async (url, options) => options?.method === "DELETE" ? null : ({ files: ["file.txt"], snapshot: "a".repeat(32) });
  permit("granted"); await saving;
  assert.equal(context.activeProjectExports.has("J"), false);
  assert.equal(destination.writes.length, 1);
});

test("failed exports release the revision lock and pending revision requests prevent new exports", async () => {
  const context = exportContext();
  const destination = folder("failed", async () => "denied");
  context.localFolders.set("P", destination);
  await context.exportProject({ id: "P" }, completed);
  assert.equal(context.activeProjectExports.has("J"), false);
  assert.match(context.folderStatus.textContent, /저장 실패/);
  context.pendingRevisionRequests.add("J");
  destination.queryPermission = async () => { throw Error("export must not start during revision POST"); };
  await context.exportProject({ id: "P" }, completed, true);
  assert.equal(context.activeProjectExports.has("J"), false);
});

test("finishing one export does not unlock revisions while another folder is still saving", async () => {
  const context = exportContext();
  let permit;
  const first = folder("first", () => new Promise(resolve => { permit = resolve; }));
  context.localFolders.set("P", first);
  const pending = context.exportProject({ id: "P" }, completed);
  context.localFolders.set("P", folder("second"));
  await context.exportProject({ id: "P" }, completed);
  assert.equal(context.activeProjectExports.get("J"), 1);
  permit("granted"); await pending;
  assert.equal(context.activeProjectExports.has("J"), false);
});

test("the chat composer disables during export and re-enables after saving", () => {
  const help = {};
  const context = {
    chatJob: null, activeProjectExports: new Map([["J", 1]]), pendingRevisionRequests: new Set(),
    composer: {}, send: {}, updateComposerButton() {}, document: { querySelector: () => help },
  };
  vm.createContext(context);
  const start = source.indexOf("  function renderChat(");
  vm.runInContext(source.slice(start, source.indexOf("    messages.replaceChildren();", start)) + "}", context);
  const job = { ...completed, game_builder: "codex_cli", project_available: true };
  context.renderChat(job);
  assert.equal(context.composer.disabled, true);
  assert.match(help.textContent, /폴더에 저장/);
  context.activeProjectExports.delete("J");
  context.renderChat(job);
  assert.equal(context.composer.disabled, false);
  context.pendingRevisionRequests.add("J");
  context.renderChat(job);
  assert.equal(context.composer.disabled, true);
  assert.match(help.textContent, /전송/);
});
