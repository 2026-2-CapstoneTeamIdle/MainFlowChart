const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appSource = fs.readFileSync(
  path.join(__dirname, "..", "CI", "CD", "LocalWeb", "static", "app.js"),
  "utf8",
);
const start = appSource.indexOf("function renderFeatures(features) {");
const end = appSource.indexOf("\nfunction renderChecklistCriterion(", start);
assert.ok(start >= 0 && end > start);

function createFeatureList() {
  const cards = [];
  const list = {
    children: cards,
    scrollTop: 0,
    get childElementCount() { return cards.length; },
    insertBefore(card, before) {
      const previousIndex = cards.indexOf(card);
      if (previousIndex >= 0) cards.splice(previousIndex, 1);
      const index = before ? cards.indexOf(before) : -1;
      cards.splice(index < 0 ? cards.length : index, 0, card);
      card.ownerList = list;
    },
  };
  return list;
}

class FakeCard {
  constructor() {
    this.dataset = {};
    this.style = { setProperty() {} };
    this.criteria = [];
    this.list = { scrollTop: 0 };
  }
  set innerHTML(markup) {
    this.criteria = [...markup.matchAll(/data-criterion-id="([^"]+)"/g)].map((match) => {
      const criterion = { dataset: { criterionId: match[1] } };
      criterion.details = { open: false, closest: () => criterion };
      criterion.querySelector = () => criterion.details;
      return criterion;
    });
    this.list = { scrollTop: 0 };
  }
  setAttribute() {}
  getBoundingClientRect() { return { top: 5, bottom: 100 }; }
  querySelectorAll(selector) {
    if (selector === ".checklist-item details") return this.criteria.map((item) => item.details);
    if (selector === ".checklist-item") return this.criteria;
    return [];
  }
  querySelector(selector) {
    if (selector === ".feature-checklist ol") return this.list;
    return null;
  }
  replaceWith(next) {
    const cards = this.ownerList.children;
    cards[cards.indexOf(this)] = next;
    next.ownerList = this.ownerList;
  }
  remove() {
    const cards = this.ownerList.children;
    cards.splice(cards.indexOf(this), 1);
  }
}

test("an open checklist detail and scroll survive a polling snapshot without details", () => {
  const featureList = createFeatureList();
  const context = vm.createContext({
    featureCount: { textContent: "" },
    featureList,
    expandedFeatureIds: new Set(["FC01"]),
    openedCriteriaByFeature: new Map(),
    checklistScrollByFeature: new Map(),
    lastFeatureRenderKey: null,
    document: { createElement: () => new FakeCard() },
    window: { innerHeight: 900, scrollBy() {} },
    escapeHtml: String,
    originLabel: String,
    featureStatusLabel: String,
    checklistStatusLabel: String,
    checklistEmptyLabel: String,
    renderChecklistCriterion: (criterion) =>
      '<li data-criterion-id="' + criterion.criterion_id + '"></li>',
  });
  vm.runInContext(appSource.slice(start, end), context);

  const feature = {
    feature_id: "FC01",
    origin: "user",
    name: "Movement",
    description: "Move the player",
    checklist_status: "ready",
    checklist_count: 1,
    checklist: [{ criterion_id: "FC01-01", title: "Moves" }],
    status: "working",
  };
  context.renderFeatures([feature]);
  featureList.children[0].criteria[0].details.open = true;
  featureList.children[0].list.scrollTop = 84;
  featureList.scrollTop = 42;

  context.renderFeatures([{ ...feature, checklist: [], checklist_status: "writing" }]);
  assert.equal(featureList.children[0].criteria.length, 0);
  context.renderFeatures([{ ...feature, status: "passed" }]);

  assert.equal(featureList.children[0].criteria[0].details.open, true);
  assert.equal(featureList.children[0].list.scrollTop, 84);
  assert.equal(featureList.scrollTop, 42);

  featureList.children[0].criteria[0].details.open = false;
  context.renderFeatures([{ ...feature, status: "failed" }]);
  assert.equal(featureList.children[0].criteria[0].details.open, false);
});
