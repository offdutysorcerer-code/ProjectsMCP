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
- `read_file(project, path)`
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

## Start server

Run:

```bat
D:\AIProjects\ProjectsMCP\StartProjectsMCP.bat
```

Local SSE endpoint:

```text
http://127.0.0.1:8090/sse
```

Expose it to ChatGPT with ngrok or another tunnel:

```text
https://YOUR-NGROK-DOMAIN/sse
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

1. 安裝 Python 3.11 或更新版本。
2. 執行 `SetupProjectsMCP.bat`。它會自動安裝 uv、Python 套件、Playwright Chromium 與 ngrok；若尚未設定 ngrok，會要求輸入 authtoken。
3. 安裝完成後可直接選擇啟動 ProjectsMCP 與 ngrok tunnel，也可日後分別執行 `StartProjectsMCP.bat`、`StartNgrokMCP.bat`。
4. 若 WinGet 的 ngrok 安裝失敗，Setup 會自動重設並更新 WinGet source 後重試一次。

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
4. Run `StartNgrokMCP.bat` only when a tunnel is required.

A fresh browser profile will be created automatically under `artifacts/browser_profile`. Existing login sessions, cookies, and browser extensions are not part of the portable package.
