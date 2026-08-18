# ProjectsMCP Platform

ProjectsMCP is now a plugin-based MCP Platform. The outer project remains `ProjectsMCP`; platform capabilities are added under `plugins/`.

## Project aliases

Configured in `config.json`:

- `ai` = `D:\AIProjects`
- `market` = `D:\MarketResearch`

## Plugins

Enabled plugins are configured in `config.json`:

```json
{
  "plugins": {
    "enabled": ["project", "browser", "git"]
  }
}
```

### Platform tools

- `list_plugins()`

### Project plugin tools

The Project plugin keeps the original ProjectsMCP tool names:

- `list_projects()`
- `list_files(project, path="")`
- `read_file(project, path)` — reads UTF-8 text files and automatically extracts text from PDFs inside configured project roots.
- `read_multiple_files(project, paths)`
- `write_file(project, path, content)`
- `append_file(project, path, content)`
- `project_tree(project, path="", max_depth=3, exclude_patterns=None)`
- `search_files(project, pattern, path="", exclude_patterns=None, max_results=200)`
- `grep_text(project, query, path="", include_patterns=None, exclude_patterns=None, case_sensitive=False, max_results=100)`
- `replace_text(project, path, old_text, new_text, dry_run=True)`

### Git plugin tools

The Git plugin uses a `git_` prefix and runs local Git commands inside configured project roots:

- `git_version()`
- `git_repository_root(project, path="")`
- `git_status(project, path="")`
- `git_diff(project, path="", staged=false, file_path="")`
- `git_log(project, path="", max_count=10)`
- `git_branch(project, path="")`
- `git_current_branch(project, path="")`
- `git_init(project, path="")`
- `git_add(project, paths, path="")` (compatibility alias for staging)
- `git_stage(project, paths, path="")`
- `git_unstage(project, paths, path="")`
- `git_commit(project, message, paths=None, path="")`
- `git_create_branch(project, branch_name, checkout=true, path="")`
- `git_checkout(project, branch_name, path="")`

Git commands automatically detect the repository root with `git rev-parse --show-toplevel`.
Paths remain constrained to the configured project root and are passed to Git relative to
the detected repository root.

The first Git plugin version intentionally avoids remote operations such as push, pull, fetch, and reset. Add them later after local workflows are stable.

### Command plugin tools

- `run_command(command, shell="cmd", cwd="", timeout_seconds=None)`
- `run_cmd(command, cwd="", timeout_seconds=None)`
- `run_powershell(command, cwd="", timeout_seconds=None)`

Commands run without an interactive console. The default command and Git timeouts are
configured in `config.json`. On timeout, ProjectsMCP terminates the full Windows process
tree and returns `timed_out`, `duration_seconds`, and captured output instead of leaving
the MCP request hanging. Output is capped by `max_command_output_bytes`.

Shell execution is centralized through `ExecutionRuntimeService`, which sits above
`ProcessService`. PowerShell execution is delegated to `PowerShellRunner`, which owns
standard `-NoProfile` / `-NonInteractive` / `-ExecutionPolicy Bypass` flags, UTF-8
console/bootstrap settings, working-directory validation, environment forwarding, and
PowerShell executable selection. `ProcessService` remains the lower-level owner of
process creation, PID capture, timeout enforcement, bounded stdout/stderr capture,
environment normalization, and process-tree cleanup.

### Browser plugin tools

The Browser plugin is backed by Playwright and uses a `browser_` prefix:

- `browser_status()`
- `browser_open(url="", headless=false)`
- `browser_goto(url)`
- `browser_back()`
- `browser_text(max_chars=12000)`
- `browser_click_text(text, exact=false)`
- `browser_fill(selector, value)`
- `browser_press(key)`
- `browser_screenshot(full_page=true)`
- `browser_close()`

Screenshots are saved under:

```text
D:\AIProjects\ProjectsMCP\artifacts\browser
```

## Browser setup

After updating dependencies, run these once in the ProjectsMCP environment:

```bat
cd /d D:\AIProjects\ProjectsMCP
pip install -r requirements.txt
python -m playwright install chromium
```

Then restart the server and refresh the connector in ChatGPT.

## A3_2 WebView2 / ChatGPT proxy plugin

The `a3_2` plugin keeps A3_2 as the browser runtime and ProjectsMCP as the MCP-facing adapter:

```text
ChatGPT / MCP client
        |
        | MCP
        v
ProjectsMCP (A0)
        |
        | HTTP 127.0.0.1:5139
        v
A3_2 WebView2 runtime
        |
        v
authenticated ChatGPT tabs
```

A3_2 remains responsible for WebView2 tabs, persistent login state, Chromium CDP input, and ChatGPT-specific DOM handling. ProjectsMCP only translates MCP tool calls into A3_2's local HTTP API.

Local settings:

```json
{
  "settings": {
    "a3_2_endpoint": "http://127.0.0.1:5139",
    "a3_2_timeout_seconds": 120
  }
}
```

Start A3_2 before using these tools. The first MCP surface intentionally does not expose arbitrary JavaScript execution.

Browser/runtime tools:

- `a3_2_status()`
- `a3_2_list_tabs()`
- `a3_2_new_tab(url="", activate=true)`
- `a3_2_close_tab(tab_id)`
- `a3_2_activate_tab(tab_id)`
- `a3_2_navigate(tab_id, input)`
- `a3_2_get_text(tab_id, max_chars=12000)`
- `a3_2_screenshot(tab_id)`

ChatGPT adapter tools:

- `a3_2_chatgpt_send_message(tab_id, message, timeout_seconds=120)`
- `a3_2_chatgpt_get_messages(tab_id)`
- `a3_2_chatgpt_get_last_response(tab_id)`

Agent registry/orchestration tools:

- `a3_2_register_agent(name, role, tab_id, instructions="")`
- `a3_2_list_agents()`
- `a3_2_unregister_agent(name)`
- `a3_2_assign_agent_task(name, task_id, objective, project, working_path="", read_scopes=None, write_scopes=None, acceptance_criteria=None)`
- `a3_2_complete_agent_task(name, task_id, status="completed")`
- `a3_2_list_agent_tasks(status="")`
- `a3_2_claim_agent_paths(name, paths, task_id="")`
- `a3_2_release_agent_paths(name, paths=None)`
- `a3_2_list_agent_path_claims()`
- `a3_2_initialize_agent(name, timeout_seconds=120)`
- `a3_2_send_to_agent(name, message, timeout_seconds=120)`

The agent registry is stored locally under `artifacts/a3_2/agents.json`, which is excluded from Git. Registration maps a logical agent name and role to an A3_2 GUID `tabId`. The existing `instructions` argument is retained for connector compatibility but is treated as long-lived **base instructions**, not task-specific scope. Registry output exposes both `baseInstructions` and the legacy `instructions` alias. Project, working path, read/write scopes, objective, and acceptance criteria belong to an assigned task instead.

The same registry file also stores orchestration tasks and cooperative path claims. An agent can have one active assigned task. Path claims are scoped by the task's `project` and `workingPath`; overlapping paths claimed by another agent in the same task workspace are rejected. Completing, cancelling, or blocking a task automatically releases claims associated with that task. Claims are coordination guards, not filesystem locks or write-permission enforcement.

A tab ID is stable during one A3_2 process but is currently recreated after an A3_2 restart, so logical agents must be rebound to the new tab IDs after restart. Rebinding to a different tab automatically clears the `initialized` flag.

Agent dispatch has two safety layers: a per-agent cooldown and a global ChatGPT cooldown shared by all registered agents. Normal sends enforce a minimum interval. If any A3_2 tab reports the ChatGPT rate-limit dialog, A0 stops further agent dispatch and applies exponential backoff of 5, 10, 20, then up to 30 minutes. `a3_2_initialize_agent` and `a3_2_send_to_agent` return structured `status`, `retryAfterSeconds`, and `cooldownUntil` fields instead of automatically retrying.

The ChatGPT send tool delegates browser-native input, submission, rate-limit detection, final-response confirmation, and assistant-message extraction to A3_2. A3_2 reports rate limiting as HTTP 429; the A0 adapter converts it into structured MCP results where appropriate.

All `a3_2_*` MCP tools opt into FastMCP structured output and declare Pydantic return contracts, so ChatGPT receives a concrete `outputSchema` for tab lists, ChatGPT messages, agent state, dispatch results, and cooldown/rate-limit responses. MCP `structuredContent` must be a JSON object, so list-style results are wrapped as objects: `a3_2_list_tabs()` returns `{ count, tabs }` and `a3_2_chatgpt_get_messages()` returns `{ count, messages }` instead of top-level arrays.

## LINE A23 proxy plugin

The `line_a23` plugin keeps the architecture `ChatGPT -> ProjectsMCP -> A23 -> LINE Desktop`.
ProjectsMCP exposes the five LINE tools and forwards each call to the local A23 Streamable HTTP endpoint configured in `config.json`:

```json
{
  "settings": {
    "line_a23_endpoint": "http://127.0.0.1:3000/mcp",
    "line_a23_timeout_seconds": 120
  }
}
```

Start A23 before ProjectsMCP:

```powershell
cd D:\AIProjects\A23-LineMCPServer研究
node src/server.js --http-mode --host 127.0.0.1 --port 3000
```

The plugin adds:

- `line_a23_status()`
- `get_line_chatroom_history_default(...)`
- `get_line_chatroom_history_long(...)`
- `get_line_chatroom_history_short(...)`
- `send_message_manual(...)`
- `send_message_auto(...)`

## Start server

Run:

```bat
D:\AIProjects\ProjectsMCP\StartProjectsMCP.bat
```

Local SSE endpoint:

```text
http://127.0.0.1:8090/sse
```

Expose it to ChatGPT with a separate tunnel project:

```text
ngrok: use A0_3-ProjectsMCP_Ngrok`r`nCloudflare: use A0_1/A0_2 ProjectsMCP Cloudflare Tunnel
```

After changing Python files, restart `StartProjectsMCP.bat`, then refresh the connector in ChatGPT.

## Runtime logs

`StartProjectsMCP.bat` writes the combined launcher, uv, mcp-proxy, and MCP server output to:

```text
D:\\AIProjects\\ProjectsMCP\\logs\\projectsmcp-YYYY-MM-DD_HH-mm-ss.log
```

Output remains visible in the console while it is written to disk. A new file is created for each launch, and log files older than 30 days are removed automatically. The `logs` directory is excluded from Git. For unattended startup, set `PROJECTSMCP_NO_PAUSE=1` so the batch file exits without waiting for a key after the server stops.

## Structure

```text
ProjectsMCP/
├── server.py
├── config.json
├── artifacts/
│   └── browser/
├── mcp_platform/
│   ├── __init__.py
│   ├── context.py
│   └── plugin_registry.py
├── plugins/
│   ├── __init__.py
│   ├── project.py
│   └── browser.py
└── services/
    ├── __init__.py
    ├── browser_service.py
    ├── config_service.py
    └── file_service.py
```

`server.py` only bootstraps the platform, creates shared services, loads enabled plugins, and registers platform-level tools. Reusable business logic belongs in `services/`. Each plugin lives in `plugins/` and exposes a `create_plugin()` factory.

## Adding a plugin

1. Create `plugins/my_plugin.py`.
2. Implement a class with `name`, `description`, and `register_tools(mcp, context)`.
3. Add a `create_plugin()` function that returns the plugin instance.
4. Add the module name, without `.py`, to `plugins.enabled` in `config.json`.
5. Restart the server and refresh the connector.

Minimal shape:

```python
class MyPlugin:
    name = "my_plugin"
    description = "What this plugin does."

    def register_tools(self, mcp, context):
        @mcp.tool()
        def my_tool() -> dict:
            return {"ok": True}


def create_plugin():
    return MyPlugin()
```

## Safety design

The Project plugin keeps the original safety model:

- All paths are resolved relative to the selected project root.
- Path traversal is blocked.
- Write operations are limited to extensions listed in `config.json`.
- Large file reads are blocked by `max_read_bytes`.
- Project scanning excludes heavy folders such as `.git`, `node_modules`, `bin`, `obj`, `dist`, `build`, and `artifacts` by default.
- `replace_text` defaults to `dry_run=true`.

The Browser plugin currently runs local Chromium through Playwright. Use it for sites you are authorized to access.

## Next plugin ideas

- Git remote plugin expansion: `git_fetch`, `git_pull`, `git_push` with confirmation rules
- ASP.NET plugin: solution/project discovery, `.csproj` reader, Razor search
- AI index plugin: project summaries, code index, semantic search
- Office plugin: Word/Excel/PowerPoint automation
- Database plugin: query approved local/private-cloud databases


---

# 中文說明

## 專案簡介

ProjectsMCP 是一個以 Plugin 為核心的 MCP Platform，目標是將各種功能模組化，例如專案管理、Git、Browser、自動化命令，以及未來的 LM Studio、Office、資料庫等插件。

目前平台已具備：

- 專案檔案管理
- Git 版本控制
- Playwright Browser 自動化
- CMD / PowerShell 指令執行
- Plugin 擴充架構

## 快速開始

1. 安裝任一可用的 Python；Setup 會透過 uv 自動準備並固定使用 Python 3.13，以符合 MCP 套件需求。
2. 執行 `SetupProjectsMCP.bat`。它只會準備本機 ProjectsMCP 所需的 uv、Python 套件與 Playwright Chromium。
3. 安裝完成後可直接啟動 `StartProjectsMCP.bat`。若需要 ngrok，請另外使用 `A0_3-ProjectsMCP_Ngrok`。
4. Internet tunnel 已從 A0 分離：ngrok 使用 A0_3；Cloudflare Named Tunnel 使用 A0_1/A0_2。

## 專案目標

本專案希望建立一個容易維護、容易擴充的 MCP Platform，而不是只服務單一功能。Browser Plugin 只是第一個插件，未來會持續加入更多能力。

## 開發原則

- Plugin 化架構
- Service 與 Plugin 分離
- 優先考量可維護性
- 盡量降低環境相依性
- 使用 Git 進行版本控制


### Desktop plugin tools

The Windows-only Desktop plugin provides visible and auditable mouse automation:

- `mouse_highlight_start(color="#00E5FF", size=64)`
- `mouse_highlight_stop()`
- `mouse_highlight_status()`
- `mouse_get_position()`
- `mouse_move(x, y)`
- `mouse_click(button="left", clicks=1)`

The highlight is a topmost, transparent, click-through glowing ring. It follows the cursor and becomes smaller/brighter while the left mouse button is pressed. Start it before automated desktop actions and stop it afterward. The overlay is implemented by `scripts/mouse_overlay.ps1` and is managed by the MCP server process.

Example operation sequence:

```text
mouse_highlight_start()
mouse_move(500, 300)
mouse_click()
mouse_highlight_stop()
```

## Portable migration and repository size

Runtime browser data is stored under `artifacts/`, including the persistent Edge/Chromium profile, caches, extensions, downloaded browser components, screenshots, and session databases. This directory is intentionally excluded by `.gitignore` and should not be copied to another computer unless a private browser profile backup is explicitly required.

Create a minimal migration package with:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\CreatePortablePackage.ps1
```

The package excludes `artifacts`, virtual environments, Python caches, logs, local environment files, and `.git` by default. Use `-IncludeGit` only when the local Git history must be included.

After extraction on another Windows computer:

1. Review `config.json` and update project root paths for that computer.
2. Run `SetupProjectsMCP.bat` to install Python dependencies and Playwright Chromium.
3. Run `StartProjectsMCP.bat`.
4. If Internet access is required, use the separate A0_3 ngrok project or A0_1/A0_2 Cloudflare tunnel project.

A fresh browser profile will be created automatically under `artifacts/browser_profile`. Existing login sessions, cookies, and browser extensions are not part of the portable package.


## 附件保存工具

啟用 `attachment` plugin 後，可使用不經 Base64 的本機附件保存流程：

- `attachment_save_file`：從 `attachment_source_directory` 內的本機暫存檔串流複製到 `attachment_save_directory`。
- `attachment_storage_info`：查看來源目錄、目的目錄、傳輸方式與檔案大小上限。

附件工具接受所有檔案類型，預設單檔上限為 1 GiB。複製時會先寫入 `.part` 檔並計算 SHA-256，成功後才原子替換正式檔案；來源與目的路徑都會限制在設定目錄內，並阻擋路徑穿越與符號連結來源。



## Local Agent asynchronous jobs

Long-running A28 / LM Studio coding tasks can be dispatched without holding an MCP request open:

- `local_agent_submit_task(...)` queues work and immediately returns a `task_id`.
- `local_agent_task_status(task_id)` reports `queued`, `running`, or the final task status.
- `local_agent_task_result(task_id)` returns the result when ready; completed results are persisted under the A28 task results directory.
- `local_agent_run_task(...)` remains for compatibility, but its blocking worker execution is offloaded with `asyncio.to_thread` so it no longer blocks the FastMCP event loop.

`local_agent_max_concurrent_jobs` controls the local dispatcher worker pool size (default: 4). Each running job starts its own A28 worker process through `ProcessService`, so multiple local Agent jobs can progress concurrently. The command plugin likewise offloads blocking command execution from the FastMCP event loop.


## A0 Runtime Telemetry / Execution Trace v2

A0 normalizes orchestration activity into a shared runtime telemetry stream covering tasks, agents/workers, MCP tool executions, resource claims, waits, dispatches, and an append-only event envelope. Each server process creates a new `bootId`. Every audited FastMCP tool invocation creates a local execution context with a `runId`, `traceId`, and root `spanId`; its started/completed/failed/cancelled lifecycle retains those same identifiers. In-process task and dispatch telemetry inherits that context through Python `contextvars` where context propagation permits. When a worker thread emits telemetry without an active context but supplies a known `task_id`, the runtime reuses correlation already stored on that task.

Identifier semantics:

- `bootId` identifies one A0 server process lifetime. A restart always creates a new value.
- `runId` identifies one top-level audited MCP tool run; any in-process child spans retain that run.
- `traceId` groups the root MCP tool and A0-internal task/dispatch activity that actually inherited or explicitly carried its correlation.
- `spanId` identifies one local audited tool span; `parentSpanId` links an in-process child span to its recorded parent. Current child state records retain inherited correlation rather than inventing spans across transports.

Correlation is deliberately local and evidence-based. A new MCP request arriving after an external Agent or Connector boundary is a **new trace** unless that transport explicitly propagates a supported correlation token. A0 does not infer relationships from timing, task wording, ChatGPT conversations, or private model reasoning.

Runtime files remain outside Git and are isolated by server profile:

- MAIN: `artifacts/runtime/`
- DEV: `artifacts/dev/runtime/`
- `events/YYYY-MM-DD.jsonl` — one normalized event per line.
- `state.json` — the latest derived state for Control Center consumption.

The DEV launcher explicitly passes `PROJECTSMCP_ENVIRONMENT`, `PROJECTSMCP_CONFIG_PATH`, and `PROJECTSMCP_ARTIFACTS_DIR` through `mcp-proxy` with `-e`; `mcp-proxy` does not pass the parent environment to its stdio server by default. This keeps 8090/MAIN and 8091/DEV from sharing configuration or runtime state.

The `runtime_telemetry` plugin exposes:

- `runtime_snapshot()` — current summary plus agents, tasks, tool executions, claims, waits, dispatches, and recent events.
- `runtime_recent_events(limit=100)` — recent normalized events.

Current producers include MCP tool audit events (`tool.started/completed/failed/cancelled`), Local Agent and Codex queue/dispatch/execution lifecycle events, and A3_2 agent/task/path-claim events. On startup, the service loads the previous `state.json`, marks prior-boot nonterminal tools/tasks/dispatches as `interrupted`, marks held claims and active waits as `stale`, normalizes busy agents, then immediately writes state under the new `bootId`. These labels describe lost in-memory continuity after restart, not a newly observed remote failure. Per-collection retention caps preserve active records and the newest terminal history so `state.json` does not grow without bound. The append-only daily JSONL event stream remains the raw audit history.

## A0 Control Center

`A0.ControlCenter` is a read-only WPF + WebView2 dashboard for runtime orchestration telemetry. It reads the selected profile's state and latest JSONL event files directly, so the dashboard remains independent from the MCP request path. MAIN uses `config.json` + `artifacts/runtime`; DEV uses `config.dev.json` + `artifacts/dev/runtime`.

Run the matching profile explicitly:

```bat
StartA0ControlCenter.bat
StartA0ControlCenter-DEV.bat
```

The footer shows the active environment and runtime path so MAIN/DEV drift is visible instead of silently mixing data.

The dashboard prominently groups Execution Traces by `traceId` / `runId`, showing the root MCP tool and chronological correlated task/dispatch records. Work without correlation is explicitly labeled as transport-boundary/uncorrelated instead of being attached to a guessed parent. The detailed Client/ChatGPT → MCP invocation panel continues to show actual structured tool parameters, and the MCP/A0 → A2A panel continues to show emitted prompt/scopes. The bridge tails only enough bytes from recent JSONL files for the latest event window instead of loading multi-megabyte files in full. It refreshes once per second by default and does not expose cancel/retry/release or other mutating operations.

## Public endpoint and connector registration

The single source of truth for the public ProjectsMCP SSE URL is
`config.json` -> `settings.endpoint.public_sse_url`. The production endpoint is:

```text
https://mcp-main.offdutylab.xyz/sse
```

`網址.txt` is a legacy human-readable pointer only. No runtime code, setup script,
plugin loader, or manifest generator reads it. Cloudflare host profiles define
tunnel routing, but do not define the ChatGPT connector endpoint.

The ChatGPT custom connector/plugin stores its endpoint when the connector is
created or refreshed. A0 does not generate or update that remote registration.
Restarting A0 terminates existing SSE sessions; the connector should reconnect to
the same stable URL. If ChatGPT keeps an old session or an old ngrok install-time
snapshot, refresh the connector. If refresh does not replace the endpoint, remove
and reinstall the connector using the production URL above, then start a new chat.

The `mcp_diagnostics()` tool reports the runtime environment, config path, artifacts root, local/public SSE URLs, tunnel provider, expected active connector endpoint, server start time and PID, and the configuration source. Its tool name and response keys are intentionally stable across server restarts. `restart_projectsmcp()` and `get_restart_status()` use the current runtime profile: MAIN targets 8090 and `artifacts/restart`, while DEV targets 8091 and `artifacts/dev/restart`.


## Codex Agent plugin

The `codex_agent` plugin dispatches coding tasks directly to the official OpenAI Codex CLI. It does not use LM Studio or the A28 LocalDeveloper worker.

Tools:

- `codex_agent_status()`
- `codex_agent_submit_task(project, working_path, objective, acceptance_criteria, constraints=None, task_id="", sandbox="workspace-write", model="", timeout_seconds=900)`
- `codex_agent_task_status(task_id)`
- `codex_agent_task_result(task_id)`
- `codex_agent_run_task(...)`

Default execution uses `codex exec --ephemeral --sandbox workspace-write <PROMPT>`. The adapter also accepts `read-only`; dangerous sandbox bypass modes are intentionally not exposed. The generated worker prompt forbids commit, push, reset, or Git history rewriting.

Windows prerequisite: install the official Codex CLI, authenticate it with ChatGPT, and verify `codex --version` plus `codex login status` before starting ProjectsMCP.


### Startup executable registry

A0 creates one `ExecutableRegistry` during server startup and freezes full executable paths for `python`, `uv`, `git`, `node`, `pwsh`, `powershell`, `cmd`, optional `bash`, and `codex`. Execution Runtime, Git, Codex Agent, and Local Agent consume that shared startup snapshot instead of repeatedly resolving PATH during tool calls. Restart A0 after changing PATH or installing/upgrading an executable so the registry can refresh.

`bash` is an optional Execution Runtime target, not a replacement for PowerShell. On Windows, A0 prefers a concrete Git Bash installation and deliberately avoids treating the legacy/WSL `bash.exe` launcher as usable merely because the executable file exists; without a discoverable Git Bash runtime, `shell=bash` is unavailable while CMD and PowerShell continue normally. On Linux, the registry may resolve Bash through the normal executable search path.


## Command preflight / normalization

Before `run_cmd`, `run_powershell`, or `run_command` launches a child process, A0 now runs a shared `CommandPreflightChecker`. It validates shell selection, frozen executable availability, working directory, NUL characters, selected PowerShell 5.1 versus 7 compatibility, known external commands, literal `Import-Module` paths, and common CMD/PowerShell syntax-mixing or quoting risks. Fatal findings return `preflight_failed` without creating a child process; warnings are attached to the execution result. Full process environment values remain internal and only a small UTF-8 readiness summary is exposed in the preflight result.


## Error classification and controlled recovery

The DEV execution runtime classifies command outcomes before deciding whether any recovery is safe. Current categories include success, success-with-stderr, timeout, command-not-found, execution-policy, missing path/module, preflight failure, and generic process errors. Recovery is intentionally conservative: unambiguous CMD-style `cd /d` used inside PowerShell may be normalized to `Set-Location -LiteralPath` before launch, while command-not-found may be retried at most once only when the Startup Executable Registry already contains a frozen full path for that command. Timeouts, missing cwd/module, and low-confidence failures are not automatically retried. Every repair is returned as structured recovery metadata with its phase, reason, validation status, and retry count.


## Known Issues Registry / Preventive Rules

`known_issues.json` is the versioned source of preventive execution rules. `KnownIssuesRegistry` loads it at A0 startup and applies only rules whose status is `active` and whose evidence flags have both `recovery_validated=true` and `validator_passed=true`. Candidate rules are inert and cannot change execution.

The registry supports an explicit candidate lifecycle: `register_candidate(...)` records an observation, while `promote(...)` refuses activation unless both recovery validation and validator success are supplied. Active rule hits are returned under `known_issues.prevented`, including the rule ID and before/after command text, so Control Center can later count prevented incidents.

Current validated DEV rules prevent unambiguous CMD-style `cd /d` from reaching PowerShell and, for PowerShell only, replace known CLI tokens with the frozen Startup Executable Registry path. A CMD full-path rewrite was deliberately rejected after integration validation exposed `cmd.exe /s /c` quoting incompatibility; it remains excluded rather than being promoted from unit-test evidence alone.


## Seeded historical PowerShell / execution issues

DEV now seeds the historical execution problem backlog into `known_issues.json`. Policies are explicitly separated into `preventive` rules, which may safely change execution before launch, and `classify_only` rules, which may detect/report/contain a problem but must not rewrite ambiguous commands. Covered categories include execution policy, startup executable/PATH drift, missing uv/python/git-style CLIs, UTF-8/Chinese output, quoting risk, cwd validation, PowerShell 5.1/7 compatibility, command timeout, process-tree/orphan cleanup, missing PowerShell modules, and CMD/PowerShell syntax mismatch. Timeout remains non-retryable and ProcessService now reports `process_tree_terminated` after timeout cleanup. Missing modules and ambiguous quoting are intentionally not auto-installed or auto-rewritten.


## Execution Runtime Health contract

A0 exposes `executionRuntimeHealth` in both `runtime_snapshot()` and persisted RuntimeTelemetry `state.json`. The aggregation is UI-neutral and is computed from retained `run_command`, `run_cmd`, and `run_powershell` tool executions. It includes retained-window success/failure counts and success rate, timeouts, confirmed process-tree termination, controlled recovery/retry counts, Known Issues prevention hits, shell breakdowns, classification counts, and Known Issue rule-hit counts.

The current Control Center renders this contract in a replaceable `Execution Runtime Health` section. The UI is intentionally not the owner of the aggregation logic, so a future Control Center redesign can replace or remove the current section while continuing to consume the same runtime-state contract. These figures are retained-window telemetry rather than lifetime counters; older records created before classification metadata existed may appear as `unknown` until they age out of the retained window.
