const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/app.js"), "utf8");

function setup() {
  let resolve, reject;
  const response = new Promise((done, fail) => { resolve = done; reject = fail; });
  const events = [], renders = [], toasts = [];
  let polls = 0;
  const context = {
    currentJobId: "A", currentJob: { job_id: "A", preview_status: "unavailable" }, previewButton: {},
    pollRequestSequence: 0, lastAppliedPollSequence: 0,
    api: () => response, window: { dispatchEvent: event => events.push(event) },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    renderJob: job => renders.push(job), startPolling: () => { polls++; }, showToast: text => toasts.push(text),
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("async function openOrBuildPreview("), source.indexOf("function renderFeatureWorkspace(")), context);
  return { context, resolve, reject, events, renders, toasts, polls: () => polls };
}

test("late Preview response updates its original job without replacing another project's screen", async () => {
  const env = setup();
  const pending = env.context.openOrBuildPreview();
  env.context.currentJobId = "B";
  const job = { job_id: "A", preview_status: "building" };
  env.resolve(job); await pending;
  assert.equal(env.renders.length, 0);
  assert.equal(env.polls(), 0);
  assert.equal(env.toasts.length, 0);
  assert.equal(env.events[0].type, "mainflow:job-update");
  assert.equal(env.events[0].detail, job);
});

test("Preview response renders and polls when the original project remains selected", async () => {
  const env = setup();
  const pending = env.context.openOrBuildPreview();
  const job = { job_id: "A", preview_status: "building" };
  env.resolve(job); await pending;
  assert.deepEqual(env.renders, [job]);
  assert.equal(env.polls(), 1);
  assert.equal(env.context.lastAppliedPollSequence, 1);
});

test("late Preview errors cannot change another project's button or show an unrelated error", async () => {
  const env = setup();
  const pending = env.context.openOrBuildPreview();
  env.context.currentJobId = "B"; env.context.previewButton.disabled = true;
  env.reject(new Error("A failed")); await pending;
  assert.equal(env.context.previewButton.disabled, true);
  assert.equal(env.toasts.length, 0);
});

test("the renderer rejects mismatched job IDs before dispatching project updates", () => {
  const prefix = source.slice(source.indexOf("function renderJob("), source.indexOf("  const reviewKey", source.indexOf("function renderJob(")));
  const context = { currentJobId: "B" };
  vm.createContext(context);
  vm.runInContext(prefix + 'throw new Error("must not render mismatched job"); }', context);
  context.renderJob({ job_id: "A" });
});
