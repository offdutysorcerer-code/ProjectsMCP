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
