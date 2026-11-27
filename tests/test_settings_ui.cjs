const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.join(__dirname, "../CI/CD/LocalWeb/static");

test("mascot preference survives reload and stops and restarts animation", () => {
  const storage = new Map([["mainflow.chickEnabled", "false"]]);
  let change, frame, scheduled = 0, cancelled = 0;
  const toggle = { addEventListener(name, callback) { change = callback; } };
  const lane = { clientWidth: 220 };
  const sprite = { style: {} };
  const chick = { clientWidth: 100, clientHeight: 80, dataset: {}, parentElement: lane,
    style: { setProperty() {} }, querySelector: () => sprite };
  const context = {
    document: { hidden: false, addEventListener() {},
      querySelector: selector => selector === "#sidebar-chick" ? chick : toggle },
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    performance: { now: () => 0 },
    requestAnimationFrame(callback) { frame = callback; scheduled++; return scheduled; },
    cancelAnimationFrame() { cancelled++; },
  };
  vm.runInNewContext(fs.readFileSync(path.join(root, "sidebar-chick.js"), "utf8"), context);
  assert.equal(toggle.checked, false);
  assert.equal(lane.hidden, true);
  assert.equal(scheduled, 0);
  toggle.checked = true; change();
  assert.equal(lane.hidden, false);
  assert.equal(storage.get("mainflow.chickEnabled"), "true");
  frame(50);
  assert.ok(scheduled >= 2);
  toggle.checked = false; change();
  assert.equal(lane.hidden, true);
  assert.equal(storage.get("mainflow.chickEnabled"), "false");
  const before = scheduled;
  frame(100);
  assert.equal(scheduled, before);
  assert.equal(cancelled, 2);
});

test("settings expose labeled switches and supplied logo with theme-aware activity", () => {
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  for (const id of ["dark-mode-toggle", "chick-enabled-toggle", "completion-notifications"]) {
    assert.match(html, new RegExp(`id="${id}"[^>]*role="switch"`));
  }
  assert.match(html, /gamman-tool-logo\.png" alt="겜만툴"/);
  assert.ok(fs.existsSync(path.join(root, "assets/gamman-tool-logo.png")));
  const css = fs.readFileSync(path.join(root, "conversation.css"), "utf8");
  assert.match(css, /body\.dark-mode \.conversation-activity[^{}]+\{ background: var\(--paper\); color: var\(--ink\);/);
});
