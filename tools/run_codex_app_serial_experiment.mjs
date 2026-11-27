// Serial Unity generation through the official Codex app-server protocol.
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import readline from "node:readline";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const seconds = ms => Math.round(ms / 100) / 10;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function options(argv) {
  const values = {};
  const flags = new Set(["dry-run", "resume", "probe", "check-resume", "reverse"]);
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i].replace(/^--/, "");
    if (!argv[i].startsWith("--")) throw new Error(`Unexpected argument: ${argv[i]}`);
    values[key] = flags.has(key) ? true : argv[++i];
    if (values[key] === undefined) throw new Error(`Missing value for --${key}`);
  }
  if (!values.workbook || !values["output-dir"]) {
    throw new Error("Required: --workbook FILE --output-dir DIR");
  }
  values.model ??= "gpt-5.6-luna";
  values.effort ??= "medium";
  values.repeats = Number(values.repeats ?? 1);
  values["max-repairs"] = Number(values["max-repairs"] ?? 2);
  values["timeout-minutes"] = Number(values["timeout-minutes"] ?? 120);
  values["build-timeout-minutes"] = Number(values["build-timeout-minutes"] ?? 45);
  if (![values.repeats, values["max-repairs"], values["timeout-minutes"], values["build-timeout-minutes"]].every(Number.isFinite)
      || values.repeats < 1 || !Number.isInteger(values.repeats)
      || values["max-repairs"] < 0 || !Number.isInteger(values["max-repairs"])
      || values["timeout-minutes"] <= 0 || values["build-timeout-minutes"] <= 0) {
    throw new Error("Invalid repeats, repair limit, or timeout");
  }
  return values;
}

function pythonJson(source, args = [], timeout = 120000) {
  const result = spawnSync("python", ["-c", source, ...args], {
    cwd: repo, encoding: "utf8", timeout, maxBuffer: 8 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) throw new Error(result.error?.message || result.stderr || "Python command failed");
  return JSON.parse(result.stdout.trim());
}

function requestsFromWorkbook(workbook) {
  return pythonJson(
    "import json,sys; from pathlib import Path; from tools.export_experiment_requests import extract_requests; print(json.dumps(extract_requests(Path(sys.argv[1])), ensure_ascii=False))",
    [workbook],
  );
}

function resolveEditor(value) {
  if (value && fs.existsSync(value)) return path.resolve(value);
  if (process.env.UNITY_EDITOR_PATH && fs.existsSync(process.env.UNITY_EDITOR_PATH)) return path.resolve(process.env.UNITY_EDITOR_PATH);
  const hub = "C:\\Program Files\\Unity\\Hub\\Editor";
  if (!fs.existsSync(hub)) throw new Error("Unity Editor not found; pass --unity-editor");
  const found = fs.readdirSync(hub).sort().reverse()
    .map(version => path.join(hub, version, "Editor", "Unity.exe"))
    .find(file => fs.existsSync(file));
  if (!found) throw new Error("Unity Editor not found; pass --unity-editor");
  return found;
}

function resolveCodex(value) {
  const candidate = value || (process.platform === "win32" ? path.join(process.env.APPDATA || "", "npm", "codex.cmd") : "codex");
  if (process.platform === "win32" && candidate.toLowerCase().endsWith(".cmd")) {
    const script = path.join(path.dirname(candidate), "node_modules", "@openai", "codex", "bin", "codex.js");
    if (!fs.existsSync(script)) throw new Error(`Codex npm entrypoint not found: ${script}`);
    return { program: process.execPath, prefix: [script] };
  }
  if (candidate.toLowerCase().endsWith(".js")) return { program: process.execPath, prefix: [candidate] };
  return { program: candidate, prefix: [] };
}

function runProcess(program, args, cwd, timeoutMs, outputFile) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const log = fs.createWriteStream(outputFile);
    const child = spawn(program, args, { cwd, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    child.stdout.pipe(log, { end: false });
    child.stderr.pipe(log, { end: false });
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      else child.kill("SIGKILL");
    }, timeoutMs);
    child.once("error", error => { clearTimeout(timer); log.end(); reject(error); });
    child.once("close", code => { clearTimeout(timer); log.end(); resolve({ code, timedOut, seconds: seconds(Date.now() - started) }); });
  });
}

class AppServer {
  constructor(executable, cwd, eventsFile) {
    this.child = spawn(executable.program, [...executable.prefix, "app-server"], { cwd, windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
    this.pending = new Map();
    this.nextId = 1;
    this.listeners = new Set();
    this.events = fs.createWriteStream(eventsFile);
    this.stderr = fs.createWriteStream(path.join(path.dirname(eventsFile), "app_server_stderr.log"));
    this.completedCommands = 0;
    this.infrastructureError = null;
    this.child.stderr.pipe(this.stderr);
    this.stderrText = "";
    this.child.stderr.on("data", chunk => { this.stderrText = (this.stderrText + String(chunk)).slice(-2000); });
    readline.createInterface({ input: this.child.stdout }).on("line", line => this.receive(line));
    this.child.once("exit", code => {
      for (const waiter of this.pending.values()) waiter.reject(new Error(`app-server exited: ${code}: ${this.stderrText}`));
      this.pending.clear();
      for (const listener of this.listeners) listener({ method: "server/exited", params: { code } });
    });
    this.child.once("error", error => {
      for (const waiter of this.pending.values()) waiter.reject(error);
      this.pending.clear();
      for (const listener of this.listeners) listener({ method: "server/exited", params: { error: error.message } });
    });
  }
  send(message) { this.child.stdin.write(JSON.stringify(message) + "\n"); }
  request(method, params, timeoutMs = 30000) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`${method} timed out`)); }, timeoutMs);
      this.pending.set(id, { resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); } });
      this.send({ id, method, params });
    });
  }
  receive(line) {
    let message;
    try { message = JSON.parse(line); } catch { return; }
    this.events.write(JSON.stringify(message) + "\n");
    const item = message.method === "item/completed" ? message.params?.item : null;
    if (item?.type === "commandExecution" && item.status === "completed" && item.exitCode === 0) {
      this.completedCommands++;
    }
    const failedToolOutput = item?.status === "failed"
      ? String(item.aggregatedOutput || item.error || "")
      : "";
    if (/app runtime provisioning service is unavailable|registered Core launch requires an installed app/i.test(failedToolOutput)) {
      this.infrastructureError = failedToolOutput.slice(0, 1000);
    }
    if (message.id !== undefined && !message.method) {
      const waiter = this.pending.get(message.id);
      if (waiter) {
        this.pending.delete(message.id);
        if (message.error) waiter.reject(new Error(JSON.stringify(message.error)));
        else waiter.resolve(message.result);
      }
    } else if (message.id !== undefined && message.method) {
      this.send({ id: message.id, error: { code: -32000, message: "Unattended experiment cannot answer interactive requests" } });
    } else for (const listener of this.listeners) listener(message);
  }
  async initialize() {
    await this.request("initialize", { clientInfo: { name: "unity_experiment", title: "Unity Experiment", version: "1.0.0" } });
    this.send({ method: "initialized", params: {} });
  }
  async turn(threadId, prompt, opts) {
    let turnId;
    const start = Date.now();
    const finished = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.listeners.delete(listener);
        reject(new Error("Codex turn timed out"));
      }, opts.timeoutMs);
      const listener = message => {
        if (message.method === "server/exited" || (message.method === "turn/completed" && (!turnId || message.params?.turn?.id === turnId))) {
          clearTimeout(timer);
          this.listeners.delete(listener);
          if (message.method === "server/exited") reject(new Error("app-server exited during turn"));
          else resolve({ status: message.params.turn.status, error: message.params.turn.error, seconds: seconds(Date.now() - start) });
        }
      };
      this.listeners.add(listener);
    });
    finished.catch(() => {});
    try {
      const response = await this.request("turn/start", {
        threadId, input: [{ type: "text", text: prompt }], cwd: opts.cwd,
        model: opts.model, effort: opts.effort, approvalPolicy: "never",
        sandboxPolicy: { type: "workspaceWrite", writableRoots: [opts.cwd], networkAccess: false },
      });
      turnId = response.turn.id;
      const result = await finished;
      return this.infrastructureError
        ? { ...result, status: "infrastructure_error", error: this.infrastructureError }
        : result;
    } catch (error) { throw error; }
  }
  close() {
    let finished = false;
    const finish = () => { if (finished) return; finished = true; this.events.end(); this.stderr.end(); };
    this.child.once("close", finish);
    this.child.stdin.end();
    setTimeout(() => { if (this.child.exitCode === null) this.child.kill(); }, 1000).unref();
    if (this.child.exitCode !== null && this.child.stdout.readableEnded) finish();
  }
  stop() {
    if (process.platform === "win32" && this.child.pid) spawnSync("taskkill", ["/PID", String(this.child.pid), "/T", "/F"], { stdio: "ignore" });
    else this.child.kill("SIGKILL");
  }
}

function usageFromRollout(threadId) {
  const home = process.env.CODEX_HOME || path.join(os.homedir(), ".codex");
  const sessions = path.join(home, "sessions");
  if (!fs.existsSync(sessions)) return null;
  const stack = [sessions];
  const found = [];
  while (stack.length) {
    for (const entry of fs.readdirSync(stack.pop(), { withFileTypes: true })) {
      const full = path.join(entry.parentPath || entry.path, entry.name);
      if (entry.isDirectory()) stack.push(full);
      else if (entry.name.startsWith("rollout-") && entry.name.endsWith(".jsonl")) {
        if (entry.name.endsWith(`${threadId}.jsonl`)) { found.push(full); continue; }
        try {
          const fd = fs.openSync(full, "r");
          const buffer = Buffer.alloc(32768);
          const length = fs.readSync(fd, buffer, 0, buffer.length, 0);
          fs.closeSync(fd);
          const firstLine = buffer.toString("utf8", 0, length).split(/\r?\n/, 1)[0];
          if (JSON.parse(firstLine).payload?.session_id === threadId) found.push(full);
        } catch { /* An unrelated or incomplete rollout. */ }
      }
    }
  }
  if (!found.length) return null;
  const fields = ["input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens"];
  const total = Object.fromEntries(fields.map(field => [field, 0]));
  let recorded = 0;
  for (const file of found) {
    let usage = null;
    for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
      if (!line || !line.includes('"token_usage_record"')) continue;
      try {
        const item = JSON.parse(line);
        if (item.type === "token_usage_record") usage = item.payload?.thread_token_usage || usage;
      } catch { /* Incomplete final line while Codex is flushing. */ }
    }
    if (!usage) continue;
    recorded++;
    for (const field of fields) total[field] += Number(usage[field] || 0);
  }
  return recorded ? { ...total, recorded_threads: recorded, matched_threads: found.length } : null;
}

function promptFor(request) {
  return `Unity에서 실행할 수 있는 게임을 만들어줘. ${request.genre} 장르의 ${request.viewpoint} 시점으로 ${request.condition} 하는 게임을 만들어줘.`;
}

async function probeToolRuntime(executable, model, effort) {
  const workspace = path.join(repo, "workspace");
  fs.mkdirSync(workspace, { recursive: true });
  const probeDir = fs.mkdtempSync(path.join(workspace, "codex-app-runtime-probe-"));
  const marker = path.join(probeDir, "tool_probe.txt");
  const app = new AppServer(executable, probeDir, path.join(probeDir, "events.jsonl"));
  try {
    await app.initialize();
    const models = await app.request("model/list", { limit: 100 });
    const modelListed = JSON.stringify(models).includes(model);
    if (!modelListed) return { passed: false, model_listed: false, probe_dir: probeDir };
    const thread = await app.request("thread/start", {
      model, cwd: probeDir, approvalPolicy: "never", sandbox: "workspace-write",
      serviceName: "unity_experiment_probe",
    });
    const threadId = thread.thread.id;
    const escapedMarker = marker.replaceAll("'", "''");
    const turn = await app.turn(threadId,
      `Use exec_command to run exactly this PowerShell command, then report the result: Set-Content -LiteralPath '${escapedMarker}' -Value 'codex-app-probe-ok'; Get-Content -LiteralPath '${escapedMarker}'. Do not change any other files.`,
      { cwd: probeDir, model, effort, timeoutMs: 90000 },
    );
    const fileWritten = fs.existsSync(marker)
      && fs.readFileSync(marker, "utf8").trim() === "codex-app-probe-ok";
    await app.request("thread/delete", { threadId }).catch(() => {});
    return {
      passed: turn.status === "completed" && app.completedCommands > 0 && fileWritten,
      model_listed: true, turn_status: turn.status, command_completed: app.completedCommands > 0,
      file_written: fileWritten, error: turn.error || null, probe_dir: probeDir,
    };
  } finally { app.close(); }
}

function build(project, trial, editor, timeoutMinutes) {
  return pythonJson(
    "import json,sys; from pathlib import Path; from tools.unity_player_build import run_player_build; print(json.dumps(run_player_build(Path(sys.argv[1]), Path(sys.argv[2]), editor_path=sys.argv[3], timeout_minutes=float(sys.argv[4]))))",
    [project, path.join(trial, "build"), editor, String(timeoutMinutes)],
    (timeoutMinutes + 1) * 60000,
  );
}

function errorExcerpt(result) {
  const logfile = result.player_build_log_file;
  if (!logfile || !fs.existsSync(logfile)) return result.player_build_error || "No Unity build log was produced";
  const lines = fs.readFileSync(logfile, "utf8").split(/\r?\n/);
  const useful = lines.filter(line => /error CS\d+|\bException\b|\berror\b|failed/i.test(line));
  return (useful.length ? useful : lines.slice(-40)).slice(-35).join("\n").slice(-10000);
}

function appendCsv(file, row) {
  const keys = ["trial_id", "prompt_id", "genre", "model", "effort", "thread_id", "project", "setup_status", "codex_status", "build_status", "runtime_status", "repair_turns", "setup_seconds", "codex_seconds", "build_seconds", "total_seconds", "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens", "token_threads", "token_status", "error"];
  const quote = value => `"${String(value ?? "").replaceAll('"', '""')}"`;
  fs.appendFileSync(file, (!fs.existsSync(file) ? keys.join(",") + "\n" : "") + keys.map(key => quote(row[key])).join(",") + "\n", "utf8");
}

async function main() {
  const args = options(process.argv.slice(2));
  const workbook = path.resolve(args.workbook);
  const output = path.resolve(args["output-dir"]);
  const requests = requestsFromWorkbook(workbook);
  const trialIds = Object.keys(requests).flatMap(id => Array.from({ length: args.repeats }, (_, index) => `${id}-${String(index + 1).padStart(2, "0")}`));
  if (args.reverse) trialIds.reverse();
  if (args["inspect-thread"]) { console.log(JSON.stringify(usageFromRollout(args["inspect-thread"]))); return; }
  if (args["preview-prompt"]) {
    const request = requests[args["preview-prompt"]];
    if (!request) throw new Error(`Unknown prompt ID: ${args["preview-prompt"]}`);
    console.log(promptFor(request));
    return;
  }
  if (args["dry-run"]) { console.log(trialIds.join("\n")); return; }
  const editor = resolveEditor(args["unity-editor"]);
  const codex = resolveCodex(args["codex-cli"]);
  if (args.probe) {
    const result = await probeToolRuntime(codex, args.model, args.effort);
    console.log(JSON.stringify({ app_server: "connected", model: args.model, editor, ...result }));
    if (!result.passed) process.exitCode = 2;
    return;
  }
  const manifestPath = path.join(output, "manifest.json");
  if (args["check-resume"] && (!args.resume || !fs.existsSync(manifestPath))) {
    throw new Error("--check-resume requires --resume and an existing manifest.json");
  }
  const manifest = {
    surface: "codex-app-server", workbook_sha256: crypto.createHash("sha256").update(fs.readFileSync(workbook)).digest("hex"),
    model: args.model, effort: args.effort, repeats: args.repeats, max_repairs: args["max-repairs"], editor,
    order: args.reverse ? "reverse" : "forward",
    timeout_minutes: args["timeout-minutes"], build_timeout_minutes: args["build-timeout-minutes"],
  };
  if (fs.existsSync(manifestPath)) {
    if (!args.resume) throw new Error(`Output directory already contains an experiment: ${output}. Add --resume to continue it, or use a new --output-dir.`);
    const saved = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    const differences = Object.keys(manifest).filter(key => saved[key] !== manifest[key]);
    if (differences.length) throw new Error(`Cannot resume because settings differ: ${differences.map(key => `${key} (saved=${JSON.stringify(saved[key])}, current=${JSON.stringify(manifest[key])})`).join(", ")}`);
  } else if (fs.existsSync(output) && fs.readdirSync(output).length) {
    throw new Error("Output directory is not empty");
  }
  if (args["check-resume"]) { console.log(`Resume settings match: ${output}`); return; }

  const toolProbe = await probeToolRuntime(codex, args.model, args.effort);
  if (!toolProbe.passed) {
    throw new Error(`Codex app-server tool runtime unavailable; no trials started. ${JSON.stringify(toolProbe)}`);
  }
  if (!fs.existsSync(output)) fs.mkdirSync(output, { recursive: true });
  if (!fs.existsSync(manifestPath)) fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));

  const csv = path.join(output, "results.csv");
  let activeApp = null;
  process.once("SIGINT", () => { activeApp?.stop(); process.exit(130); });
  for (const trialId of trialIds) {
    const promptId = trialId.slice(0, 3);
    let trial = path.join(output, "trials", trialId);
    if (fs.existsSync(path.join(trial, "result.json")) && args.resume) continue;
    if (fs.existsSync(trial) && args.resume) {
      let attempt = 2;
      while (fs.existsSync(path.join(output, "trials", `${trialId}-attempt${String(attempt).padStart(2, "0")}`))) attempt++;
      trial = path.join(output, "trials", `${trialId}-attempt${String(attempt).padStart(2, "0")}`);
    } else if (fs.existsSync(trial)) throw new Error(`Trial already exists: ${trial}`);
    const resultFile = path.join(trial, "result.json");
    fs.mkdirSync(trial, { recursive: true });
    const project = path.join(trial, "unity_project");
    const request = requests[promptId];
    const prompt = promptFor(request);
    fs.writeFileSync(path.join(trial, "prompt.txt"), prompt);
    const row = { trial_id: trialId, prompt_id: promptId, genre: request.genre, model: args.model, effort: args.effort,
      project, setup_status: "not_started", codex_status: "not_started", build_status: "not_attempted", runtime_status: "not_tested", repair_turns: 0, token_status: "missing" };
    const started = Date.now();
    let app;
    console.log(`Starting ${trialId} (${trialIds.indexOf(trialId) + 1}/${trialIds.length})`);
    try {
      const setup = await runProcess(editor, ["-batchmode", "-nographics", "-quit", "-createProject", project, "-logFile", path.join(trial, "unity_create.log")], trial, 20 * 60000, path.join(trial, "unity_create_stdout.log"));
      row.setup_seconds = setup.seconds;
      row.setup_status = !setup.timedOut && setup.code === 0 && fs.existsSync(path.join(project, "ProjectSettings", "ProjectVersion.txt")) ? "completed" : "failed";
      if (row.setup_status !== "completed") throw new Error("Blank Unity project creation failed");
      spawnSync("git", ["init", "-q", project], { cwd: trial, stdio: "ignore" });
      app = new AppServer(codex, project, path.join(trial, "app_server_events.jsonl"));
      activeApp = app;
      await app.initialize();
      const thread = await app.request("thread/start", { model: args.model, cwd: project, approvalPolicy: "never", sandbox: "workspace-write", serviceName: "unity_experiment" });
      row.thread_id = thread.thread.id;
      const settings = { cwd: project, model: args.model, effort: args.effort, timeoutMs: args["timeout-minutes"] * 60000 };
      let first = true;
      for (let attempt = 0; attempt <= args["max-repairs"]; attempt++) {
        const instruction = first ? prompt : `Unity Windows 빌드 검증에 실패했습니다. 아래 오류를 확인해 프로젝트를 수정하고 다시 컴파일 가능하게 해주세요.\n\n${errorExcerpt(row.last_build)}\n`;
        first = false;
        const turn = await app.turn(row.thread_id, instruction, settings);
        row.codex_seconds = seconds((row.codex_seconds || 0) * 1000 + turn.seconds * 1000);
        row.codex_status = turn.status;
        if (turn.status !== "completed") { row.error = JSON.stringify(turn.error || "Codex turn failed"); break; }
        const built = build(project, trial, editor, args["build-timeout-minutes"]);
        row.last_build = built;
        row.build_seconds = seconds((row.build_seconds || 0) * 1000 + Number(built.player_build_seconds || 0) * 1000);
        row.build_status = built.player_build_status;
        row.repair_turns = attempt;
        if (row.build_status === "passed" || row.build_status === "infrastructure_error") break;
      }
      await sleep(200);
      const usage = usageFromRollout(row.thread_id);
      if (usage) {
        Object.assign(row, { input_tokens: usage.input_tokens, cached_input_tokens: usage.cached_input_tokens,
          output_tokens: usage.output_tokens, reasoning_output_tokens: usage.reasoning_output_tokens,
          total_tokens: usage.total_tokens, token_status: usage.recorded_threads === usage.matched_threads ? "recorded" : "partial",
          token_threads: usage.recorded_threads });
      }
    } catch (error) { row.error = error.message; if (row.setup_status === "completed" && row.codex_status === "not_started") row.codex_status = "infrastructure_error"; }
    finally { app?.close(); activeApp = null; }
    row.total_seconds = seconds(Date.now() - started);
    if (row.last_build) { row.build_log = row.last_build.player_build_log_file; row.build_output = row.last_build.player_build_output; delete row.last_build; }
    fs.writeFileSync(resultFile, JSON.stringify(row, null, 2));
    appendCsv(csv, row);
    writeSummary(output);
    console.log(`Finished ${trialId}: ${row.build_status}, ${row.total_tokens ?? "tokens unavailable"} tokens, ${row.total_seconds}s`);
    if (row.setup_status !== "completed") { console.error("Stopping: Unity setup failed"); break; }
    if (row.codex_status === "infrastructure_error" || /unauthorized|usageLimitExceeded|rate.limit/i.test(row.error || "")) {
      console.error("Stopping: Codex infrastructure or account failure"); break;
    }
  }
}

function writeSummary(output) {
  const trialRoot = path.join(output, "trials");
  const rows = fs.readdirSync(trialRoot, { withFileTypes: true })
    .filter(item => item.isDirectory() && fs.existsSync(path.join(trialRoot, item.name, "result.json")))
    .map(item => JSON.parse(fs.readFileSync(path.join(trialRoot, item.name, "result.json"), "utf8")));
  const count = rows.length;
  const buildPassed = rows.filter(row => row.build_status === "passed").length;
  const tokenRows = rows.filter(row => row.token_status === "recorded");
  const totalTokens = tokenRows.reduce((sum, row) => sum + Number(row.total_tokens || 0), 0);
  const average = key => count ? Math.round(rows.reduce((sum, row) => sum + Number(row[key] || 0), 0) / count * 10) / 10 : null;
  const summary = {
    surface: "codex-app-server", trials_finished: count, build_passed: buildPassed,
    build_success_rate: count ? buildPassed / count : null,
    token_rows_recorded: tokenRows.length, total_tokens: totalTokens,
    average_codex_seconds: average("codex_seconds"), average_total_seconds: average("total_seconds"),
    runtime_validation: "not performed; build success only means Windows player build passed",
  };
  fs.writeFileSync(path.join(output, "summary.json"), JSON.stringify(summary, null, 2));
  const lines = [
    "# Codex App Server 직렬 Unity 실험", "",
    `- 완료: ${count}회`, `- Windows 빌드 성공: ${buildPassed}회 / ${count}회`,
    `- 기록된 총 토큰: ${totalTokens} (${tokenRows.length}/${count}회)`,
    `- 평균 Codex 처리 시간: ${summary.average_codex_seconds ?? "N/A"}초`, "",
    "| 실행 | 장르 | Codex | Windows 빌드 | 소요 시간(초) | 총 토큰 | 수정 횟수 |",
    "|---|---|---|---|---:|---:|---:|",
    ...rows.map(row => `| ${row.trial_id} | ${row.genre} | ${row.codex_status} | ${row.build_status} | ${row.total_seconds} | ${row.total_tokens ?? "N/A"} | ${row.repair_turns} |`),
    "", "빌드 성공은 Game.exe 생성 기준이며, 플레이 가능성은 별도로 검증해야 합니다.",
    "Codex 데스크톱 UI에서 사람이 직접 시작한 대화가 아닌 공식 app-server로 시작한 대화입니다.", "",
  ];
  fs.writeFileSync(path.join(output, "summary.md"), lines.join("\n"));
}

main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
