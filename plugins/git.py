from __future__ import annotations

from typing import Any

from mcp_platform.context import PlatformContext


class GitPlugin:
    """Local Git version-control plugin."""

    name = "git"
    description = "Inspect and automate local Git status, diff, log, branches, staging, and commits."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        git_service = context.git_service

        @mcp.tool()
        def git_version() -> dict[str, Any]:
            """Report whether Git is discoverable by the MCP server process."""
            return git_service.version()

        @mcp.tool()
        def git_repository_root(project: str, path: str = "") -> dict[str, Any]:
            """Return the detected repository root for a configured project path."""
            return git_service.repository_root(project, path)

        @mcp.tool()
        def git_status(project: str, path: str = "") -> dict[str, Any]:
            """Show short Git status for a configured project path."""
            return git_service.status(project, path)

        @mcp.tool()
        def git_diff(project: str, path: str = "", staged: bool = False, file_path: str = "") -> dict[str, Any]:
            """Show unstaged or staged Git diff. Optionally limit to one project-relative file."""
            return git_service.diff(project, path, staged, file_path)

        @mcp.tool()
        def git_log(project: str, path: str = "", max_count: int = 10) -> dict[str, Any]:
            """Show recent commits in compact tab-separated format."""
            return git_service.log(project, path, max_count)

        @mcp.tool()
        def git_branch(project: str, path: str = "") -> dict[str, Any]:
            """List local Git branches."""
            return git_service.branch(project, path)

        @mcp.tool()
        def git_current_branch(project: str, path: str = "") -> dict[str, Any]:
            """Show the current Git branch name."""
            return git_service.current_branch(project, path)

        @mcp.tool()
        def git_init(project: str, path: str = "") -> dict[str, Any]:
            """Initialize a Git repository inside a configured project path."""
            return git_service.init(project, path)

        @mcp.tool()
        def git_add(project: str, paths: list[str], path: str = "") -> dict[str, Any]:
            """Stage project-relative paths. Use ['.'] only when intentionally staging everything."""
            return git_service.add(project, paths, path)

        @mcp.tool()
        def git_stage(project: str, paths: list[str], path: str = "") -> dict[str, Any]:
            """Stage project-relative paths."""
            return git_service.add(project, paths, path)

        @mcp.tool()
        def git_unstage(project: str, paths: list[str], path: str = "") -> dict[str, Any]:
            """Unstage project-relative paths without changing working-tree files."""
            return git_service.unstage(project, paths, path)

        @mcp.tool()
        def git_commit(project: str, message: str, paths: list[str] | None = None, path: str = "") -> dict[str, Any]:
            """Create a commit. When paths are provided, they are staged first."""
            return git_service.commit(project, message, paths, path)

        @mcp.tool()
        def git_create_branch(project: str, branch_name: str, checkout: bool = True, path: str = "") -> dict[str, Any]:
            """Create a local branch, optionally checking it out immediately."""
            return git_service.create_branch(project, branch_name, checkout, path)

        @mcp.tool()
        def git_checkout(project: str, branch_name: str, path: str = "") -> dict[str, Any]:
            """Checkout an existing local branch."""
            return git_service.checkout(project, branch_name, path)


def create_plugin() -> GitPlugin:
    return GitPlugin()
