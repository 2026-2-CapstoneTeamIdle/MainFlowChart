const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("mascot starts cropped and every animation frame stays within the sprite sheet", () => {
  const sprite = { style: {} };
  const chick = {
    clientWidth: 100, clientHeight: 80, dataset: {}, style: { setProperty() {} },
    parentElement: { clientWidth: 220 }, querySelector: () => sprite,
  };
  let callback;
  const context = {
    document: { querySelector: () => chick, hidden: false, addEventListener() {} },
    matchMedia: () => ({ matches: false }), performance: { now: () => 0 },
    requestAnimationFrame: fn => { callback = fn; },
    // Force running and falling so the recovery frames are covered too.
    Math: Object.assign(Object.create(Math), { random: () => .05 }),
  };
  const source = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/sidebar-chick.js"), "utf8");
  vm.runInNewContext(source, context);
  assert.ok(sprite.style.backgroundPosition, "crop must be set synchronously before the first paint");
  const seen = new Set();
  const positions = new Set();
  const crops = new Set();
  for (let time = 0; time < 15000; time += 50) {
    callback(time);
    seen.add(chick.dataset.motion);
    positions.add(chick.style.transform);
    crops.add(sprite.style.backgroundPosition);
    const [offsetX, offsetY] = sprite.style.backgroundPosition.split(" ").map(parseFloat);
    const [sheetWidth, sheetHeight] = sprite.style.backgroundSize.split(" ").map(parseFloat);
    assert.ok(offsetX < -80 && offsetY < 0, "never display title columns at the top left");
    assert.ok(-offsetX + parseFloat(sprite.style.width) <= sheetWidth + .01);
    assert.ok(-offsetY + parseFloat(sprite.style.height) <= sheetHeight + .01);
  }
  assert.ok(seen.has("run"));
  assert.ok(seen.has("fall"));
  assert.ok(positions.size > 10, "mascot must move horizontally");
  assert.ok(crops.size > 6, "sprite frames must advance");
});

test("requested mascot animation moves even with OS reduced motion enabled", () => {
  const sprite = { style: {} };
  const chick = { clientWidth: 100, clientHeight: 80, dataset: {}, style: { setProperty() {} },
    parentElement: { clientWidth: 220 }, querySelector: () => sprite };
  let callback;
  const context = { document: { querySelector: () => chick, hidden: false, addEventListener() {} },
    matchMedia: () => ({ matches: true }), performance: { now: () => 0 },
    requestAnimationFrame: fn => { callback = fn; },
    Math: Object.assign(Object.create(Math), { random: () => .5 }) };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/sidebar-chick.js"), "utf8"), context);
  callback(0); const initial = chick.style.transform;
  for (let time = 50; time < 500; time += 50) callback(time);
  assert.notEqual(chick.style.transform, initial);
  const beforeHidden = chick.style.transform;
  context.document.hidden = true;
  callback(550); callback(600);
  assert.equal(chick.style.transform, beforeHidden, "background tabs should not advance movement");
});

test("mascot keeps roaming over time and restarts its loop when the tab becomes visible", () => {
  const sprite = { style: {} };
  const chick = { clientWidth: 100, clientHeight: 80, dataset: {}, style: { setProperty() {} },
    parentElement: { clientWidth: 220 }, querySelector: () => sprite };
  let callback, visibility, clock = 0;
  const document = { querySelector: () => chick, hidden: false,
    addEventListener: (name, fn) => { if (name === "visibilitychange") visibility = fn; } };
  const context = { document, performance: { now: () => clock },
    requestAnimationFrame: fn => { callback = fn; return 1; }, cancelAnimationFrame() {},
    Math: Object.assign(Object.create(Math), { random: () => .5 }) };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/sidebar-chick.js"), "utf8"), context);
  for (clock = 0; clock < 300000; clock += 50) callback(clock);
  assert.notEqual(chick.dataset.motion, "idle");
  document.hidden = true; visibility();
  clock += 60000; document.hidden = false; visibility();
  const previous = chick.style.transform;
  for (let i = 0; i < 10; i++) { clock += 50; callback(clock); }
  assert.notEqual(chick.style.transform, previous);
});
