from __future__ import annotations

from typing import Any

from mcp_platform.context import PlatformContext


class ProjectPlugin:
    """Local project/file management plugin.

    This plugin preserves the original ProjectsMCP tool names so current clients do
    not need to change while the server evolves into MCP Platform.
    """

    name = "project"
    description = "Browse, search, read, and safely edit configured local project files."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        file_service = context.file_service

        @mcp.tool()
        def list_projects() -> dict[str, Any]:
            """List configured project aliases and their root paths."""
            return file_service.list_projects()

        @mcp.tool()
        def list_files(project: str, path: str = "") -> dict[str, Any]:
            """List files and folders inside a project-relative directory."""
            return file_service.list_files(project, path)

        @mcp.tool()
        def read_file(project: str, path: str) -> dict[str, Any]:
            """Read a UTF-8 text file from a project."""
            return file_service.read_file(project, path)

        @mcp.tool()
        def read_multiple_files(project: str, paths: list[str]) -> dict[str, Any]:
            """Read multiple UTF-8 text files from a project. Individual failures are returned per file."""
            return file_service.read_multiple_files(project, paths)

        @mcp.tool()
        def write_file(project: str, path: str, content: str) -> dict[str, Any]:
            """Create or overwrite a UTF-8 text file inside a project."""
            return file_service.write_file(project, path, content)

        @mcp.tool()
        def append_file(project: str, path: str, content: str) -> dict[str, Any]:
            """Append UTF-8 text to a file inside a project. Creates the file if needed."""
            return file_service.append_file(project, path, content)

        @mcp.tool()
        def project_tree(
            project: str,
            path: str = "",
            max_depth: int = 3,
            exclude_patterns: list[str] | None = None,
        ) -> dict[str, Any]:
            """Return a recursive project tree with depth control and default excludes."""
            return file_service.project_tree(project, path, max_depth, exclude_patterns)

        @mcp.tool()
        def search_files(
            project: str,
            pattern: str,
            path: str = "",
            exclude_patterns: list[str] | None = None,
            max_results: int = 200,
        ) -> dict[str, Any]:
            """Search project files by glob pattern, such as '*.py' or 'src/**/*.cs'."""
            return file_service.search_files(project, pattern, path, exclude_patterns, max_results)

        @mcp.tool()
        def grep_text(
            project: str,
            query: str,
            path: str = "",
            include_patterns: list[str] | None = None,
            exclude_patterns: list[str] | None = None,
            case_sensitive: bool = False,
            max_results: int = 100,
        ) -> dict[str, Any]:
            """Search text inside common source and document files."""
            return file_service.grep_text(
                project,
                query,
                path,
                include_patterns,
                exclude_patterns,
                case_sensitive,
                max_results,
            )

        @mcp.tool()
        def replace_text(
            project: str,
            path: str,
            old_text: str,
            new_text: str,
            dry_run: bool = True,
        ) -> dict[str, Any]:
            """Replace exact text in one file. Defaults to dry_run=True for safety."""
            return file_service.replace_text(project, path, old_text, new_text, dry_run)


def create_plugin() -> ProjectPlugin:
    return ProjectPlugin()
