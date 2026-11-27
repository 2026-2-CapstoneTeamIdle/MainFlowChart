const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/app.js"), "utf8");

function page(storage = new Map()) {
  const context = {
    notificationHistoryKey: "history", currentJobId: "job", enabled: true,
    sounds: [], notifications: [], observedNotificationStates: new Map(),
    window: { localStorage: {
      getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value),
    } },
  };
  context.notificationSettingEnabled = () => context.enabled;
  context.playNotificationTone = kind => context.sounds.push(kind);
  context.showSystemNotification = (...args) => context.notifications.push(args);
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("function loadNotificationHistory("), source.indexOf("function updateCustomImageState(")), context);
  context.notifiedMilestones = context.loadNotificationHistory();
  return context;
}

test("a notified failure does not alert again after a page reload", () => {
  const storage = new Map();
  const job = { job_id: "failed-job", status: "failed" };
  const first = page(storage);
  first.notifyJobMilestone(job, "terminal");
  first.notifyJobMilestone(job, "terminal");
  assert.equal(first.sounds.length, 1);
  const reopened = page(storage);
  reopened.notifyJobMilestone(job, "terminal");
  assert.equal(reopened.sounds.length, 0);
  assert.equal(reopened.notifications.length, 0);
});

test("restored historical results stay silent but new revisions and jobs alert", () => {
  const context = page();
  const old = { job_id: "old", status: "failed", revision_status: "failed", revision_messages: [{}, {}] };
  context.rememberJobMilestones(old);
  context.notifyJobMilestone(old, "terminal");
  context.notifyJobMilestone(old, "revision");
  assert.equal(context.sounds.length, 0);
  context.notifyJobMilestone({ ...old, revision_status: "completed", revision_messages: [{}, {}, {}, {}] }, "revision");
  context.notifyJobMilestone({ job_id: "new", status: "completed" }, "terminal");
  assert.equal(context.sounds.length, 2);
});

test("restoring an active job still notifies when it later finishes", () => {
  const context = page();
  const job = { job_id: "active", status: "running" };
  context.rememberJobMilestones(job);
  context.notifyJobMilestone({ ...job, status: "failed" }, "terminal");
  assert.equal(context.sounds.length, 1);
  const conversation = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/conversation.js"), "utf8");
  assert.match(conversation, /observeJobNotifications\(notification\)/);
  assert.doesNotMatch(conversation, /notifyJobMilestone\(/);
});

test("refreshing a failed page is silent even with no saved notification history", () => {
  for (let reload = 0; reload < 5; reload++) {
    const context = page();
    context.window.localStorage.getItem = () => { throw new Error("storage blocked"); };
    context.window.localStorage.setItem = () => { throw new Error("storage blocked"); };
    const job = { job_id: "failed", status: "failed", revision_status: "failed", revision_messages: [{}, {}] };
    for (let poll = 0; poll < 20; poll++) context.observeJobNotifications(job);
    assert.equal(context.sounds.length, 0);
    assert.equal(context.notifications.length, 0);
  }
});

test("only an observed active-to-failed transition triggers a failure notification", () => {
  const context = page();
  context.observeJobNotifications({ job_id: "active", status: "running" });
  const failure = { job_id: "active", status: "failed" };
  context.observeJobNotifications(failure);
  context.observeJobNotifications(failure); // background observer and selected-project renderer
  assert.equal(context.sounds.length, 1);
  assert.equal(context.notifications.length, 1);
  assert.match(context.notifications[0][0], /게임 생성 실패/);
  const refreshed = page();
  refreshed.observeJobNotifications(failure);
  assert.equal(refreshed.notifications.length, 0);
});

test("feature and revision notifications require their own state transitions", () => {
  const context = page();
  const job = { job_id: "project", status: "analyzing_features", features: [], feature_revision: 0 };
  context.observeJobNotifications(job);
  job.status = "awaiting_confirmation";
  context.observeJobNotifications(job);
  context.observeJobNotifications(job);
  assert.equal(context.notifications.length, 1);
  job.status = "running";
  context.observeJobNotifications(job);
  job.status = "completed";
  context.observeJobNotifications(job);
  job.revision_status = "running"; job.revision_messages = [{}];
  context.observeJobNotifications(job);
  job.revision_status = "failed"; job.revision_messages.push({});
  context.observeJobNotifications(job);
  context.observeJobNotifications(job);
  assert.equal(context.notifications.length, 3);
  assert.match(context.notifications[2][0], /게임 수정 실패/);
});

test("enabling notifications does not replay events observed while disabled", () => {
  const context = page();
  const job = { job_id: "disabled", status: "awaiting_confirmation", feature_revision: 0, features: [] };
  context.enabled = false;
  context.notifyJobMilestone(job, "feature");
  context.enabled = true;
  context.notifyJobMilestone(job, "feature");
  assert.equal(context.sounds.length, 0);
  context.notifyJobMilestone({ ...job, feature_revision: 1 }, "feature");
  assert.equal(context.sounds.length, 1);
});
