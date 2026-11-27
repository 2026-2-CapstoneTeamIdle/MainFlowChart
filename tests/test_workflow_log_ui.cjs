const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("compact logs retain stages, repairs and errors while hiding agent heartbeats", () => {
  const source = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/app.js"), "utf8");
  const start = source.indexOf("function importantWorkflowLogs(");
  const end = source.indexOf("function renderWorkflowLog(", start);
  const context = {};
  vm.runInNewContext(source.slice(start, end), context);
  const lines = ["[FLOW] 게임 로직을 설계합니다.", "[AGENT][context] 계속 처리 중",
    "[AGENT][repair] Unity 오류 수정", "ValueError: invalid route", "[RESULT] 완료"];
  const result = context.importantWorkflowLogs(lines);
  assert.deepEqual(Array.from(result), [lines[0], lines[2], lines[3], lines[4]]);
  assert.equal(lines.length, 5, "full logs must remain available");
});

test("follow-up requests own separate log ranges below their user messages", () => {
  const source = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/app.js"), "utf8");
  const context = {};
  vm.runInNewContext(source.slice(source.indexOf("function workflowLogTurns("), source.indexOf("const expandedLogRows")), context);
  const logs = ["generation", "generation done", "repair one", "repair one done", "repair two"];
  const job = { logs, revision_messages: [
    { role: "user", content: "first", log_start: 2 }, { role: "assistant", content: "done" },
    { role: "user", content: "second", log_start: 4 },
  ] };
  const result = context.workflowLogTurns(job);
  assert.deepEqual(Array.from(result.initial), logs.slice(0, 2));
  assert.deepEqual(Array.from(result.revisions.get(0)), logs.slice(2, 4));
  assert.deepEqual(Array.from(result.revisions.get(2)), logs.slice(4));
  job.log_offset = 2; job.logs = logs.slice(2);
  const truncated = context.workflowLogTurns(job);
  assert.equal(truncated.initial.length, 0);
  assert.deepEqual(Array.from(truncated.revisions.get(0)), logs.slice(2, 4));
});

test("compact description shows only the latest operation without raw tags", () => {
  const source = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/app.js"), "utf8");
  const context = {};
  vm.runInNewContext(source.slice(source.indexOf("function latestWorkflowDescription("), source.indexOf("function workflowLogTurns(")), context);
  assert.equal(context.latestWorkflowDescription(["[FLOW] 설계 시작", "[AGENT][edit] 파일 수정 중"]), "파일 수정 중");
  assert.equal(context.latestWorkflowDescription([]), "작업 기록을 기다리고 있습니다…");
  assert.ok(context.latestWorkflowDescription(["[FLOW] " + "가".repeat(200)]).length <= 101);
});

test("detailed logs group repeated messages into a few major stages without losing raw lines", () => {
  const source = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/app.js"), "utf8");
  const context = {};
  vm.runInNewContext(source.slice(source.indexOf("function groupWorkflowLogs("), source.indexOf("const expandedLogRows")), context);
  const logs = ["[WEB] 작업 abc의 Feature 분석을 시작합니다.",
    "[FLOW] 승인된 Feature별 Checklist를 작성합니다.",
    ...Array(50).fill("[AGENT][context] Codex가 계속 처리 중입니다."),
    "[FLOW] 게임 로직을 설계합니다.", "[AGENT][edit] 코드 수정 중",
    "[FLOW] Unity 컴파일·Play Mode 검증", "[AGENT][repair] 오류 수정 1/6",
    "[AGENT][context] 검사 중", "[RESULT] 완료"];
  const groups = context.groupWorkflowLogs(logs);
  assert.equal(groups.length, 5);
  assert.equal(groups.reduce((sum, group) => sum + group.logs.length, 0), logs.length);
  assert.equal(groups[1].title, "체크리스트 작성");
  assert.equal(groups[1].logs.length, 51);
  assert.equal(groups[3].title, "Unity 검증 및 오류 수리");
});
