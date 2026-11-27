const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

test("project model restoration overrides another provider's global selection", () => {
  const source = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/app.js"), "utf8");
  const context = {
    activeAgentBuilder: "claude_code",
    agentHarnessCatalog: {
      codex_cli: { models: [["luna", "Luna"], ["astra", "Astra"]], efforts: ["medium", "high"], defaultModel: "astra", defaultEffort: "high" },
      claude_code: {},
    },
    agentHarnessSelections: { codex_cli: { model: "astra", effort: "high" } },
    gameBuilder: { value: "codex_cli" },
    agentModel: {}, agentReasoningEffort: {}, agentHarnessSettings: {},
    agentFastModeField: {}, agentSettingsHelp: {},
    replaceSelectOptions(select, entries, selected) { select.value = selected; },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("function updateAgentHarnessSettings("), source.indexOf("function notificationSettingEnabled(")), context);
  context.updateAgentHarnessSettings({ restore: { agent_model: "luna", agent_reasoning_effort: "medium" } });
  assert.equal(context.agentModel.value, "luna");
  assert.equal(context.agentReasoningEffort.value, "medium");
  assert.equal(context.activeAgentBuilder, "codex_cli");
  assert.equal(context.agentHarnessSelections.claude_code, undefined);
  const conversation = fs.readFileSync(path.join(__dirname, "../CI/CD/LocalWeb/static/conversation.js"), "utf8");
  assert.match(conversation, /updateAgentHarnessSettings\(\{ restore: project\.draft/);
});
