from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.executable_registry import ExecutableRegistry
from services.file_service import FileService
from services.process_service import ProcessService


class GitService:
    """Safe wrapper around local git commands for configured projects.

    The service never uses shell=True and always resolves paths through FileService
    so git operations stay inside configured project roots.
    """

    def __init__(
        self,
        file_service: FileService,
        process_service: ProcessService,
        executables: ExecutableRegistry,
        default_timeout_seconds: int = 60,
    ) -> None:
        self.file_service = file_service
        self.process_service = process_service
        self.executables = executables
        self.default_timeout_seconds = max(1, int(default_timeout_seconds))

    def _resolve_workdir(self, project: str, path: str = "") -> Path:
        workdir = self.file_service.resolve_project_path(project, path)
        if not workdir.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        if workdir.is_file():
            workdir = workdir.parent
        return workdir

    def _resolve_repo_root(self, project: str, path: str = "") -> Path:
        result = self._run_git(
            project,
            ["rev-parse", "--show-toplevel"],
            path,
            allow_failure=True,
            detect_repo=False,
        )
        if not result["ok"] or not result["stdout"]:
            raise RuntimeError(
                result["stderr"] or "The selected path is not inside a Git repository."
            )

        repo_root = Path(result["stdout"]).resolve()
        project_root = self.file_service.get_project_root(project).resolve()
        try:
            repo_root.relative_to(project_root)
        except ValueError as exc:
            raise RuntimeError(
                "Git repository root is outside the configured project root."
            ) from exc
        return repo_root

    def _resolve_relative_paths(
        self,
        project: str,
        paths: list[str] | None,
        path: str = "",
    ) -> list[str]:
        if not paths:
            return []

        repo_root = self._resolve_repo_root(project, path)
        selected_path = self._resolve_workdir(project, path)
        resolved: list[str] = []
        for item in paths:
            target = selected_path if item == "." else self.file_service.resolve_project_path(project, item)
            try:
                relative = target.relative_to(repo_root)
            except ValueError as exc:
                raise ValueError(
                    f"Git path must be inside the repository: {item}"
                ) from exc
            resolved.append(relative.as_posix() or ".")
        return resolved

    def _run_git(
        self,
        project: str,
        args: list[str],
        path: str = "",
        timeout_seconds: int | None = None,
        allow_failure: bool = False,
        detect_repo: bool = True,
    ) -> dict[str, Any]:
        requested_workdir = self._resolve_workdir(project, path)
        workdir = (
            self._resolve_repo_root(project, path)
            if detect_repo
            else requested_workdir
        )
        git_path = self.executables.get("git")
        if not git_path:
            raise RuntimeError(
                "git executable was not found when A0 started. Install Git for Windows "
                "or fix PATH, then restart the MCP server so the executable registry can refresh."
            )

        env = os.environ.copy()
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
                "GIT_ASKPASS": "",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_PAGER": "cat",
                "GIT_EDITOR": "true",
            }
        )
        timeout = self.default_timeout_seconds if timeout_seconds is None else timeout_seconds
        result = self.process_service.run(
            [git_path, *args],
            cwd=workdir,
            timeout_seconds=timeout,
            env=env,
        )
        result.update(
            {
                "project": project,
                "path": path,
                "workdir": str(workdir),
            }
        )
        if not result["ok"] and not allow_failure:
            raise RuntimeError(
                result["stderr"]
                or result["stdout"]
                or f"git command failed: {result['command']}"
            )
        return result

    def version(self) -> dict[str, Any]:
        """Report whether Git is discoverable by the MCP server process."""
        git_path = self.executables.get("git")
        return {
            "command": [git_path or "git", "--version"],
            "git_path": git_path,
            "stdout": "",
            "stderr": "" if git_path else "git executable was not found when A0 started.",
            "ok": git_path is not None,
            "diagnostic_type": "startup_registry",
            "note": (
                "This reports the frozen startup executable registry. Restart A0 to refresh discovery."
            ),
        }

    def repository_root(self, project: str, path: str = "") -> dict[str, Any]:
        requested_workdir = self._resolve_workdir(project, path)
        repo_root = self._resolve_repo_root(project, path)
        return {
            "project": project,
            "path": path,
            "requested_workdir": str(requested_workdir),
            "repo_root": str(repo_root),
            "ok": True,
        }

    def status(self, project: str, path: str = "") -> dict[str, Any]:
        return self._run_git(
            project,
            ["status", "--short", "--branch"],
            path,
            allow_failure=True,
        )

    def diff(
        self,
        project: str,
        path: str = "",
        staged: bool = False,
        file_path: str = "",
    ) -> dict[str, Any]:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file_path:
            relative_paths = self._resolve_relative_paths(project, [file_path], path)
            args.extend(["--", *relative_paths])
        return self._run_git(
            project,
            args,
            path,
            allow_failure=True,
        )

    def log(
        self,
        project: str,
        path: str = "",
        max_count: int = 10,
    ) -> dict[str, Any]:
        safe_count = max(1, min(int(max_count), 100))
        return self._run_git(
            project,
            [
                "log",
                f"--max-count={safe_count}",
                "--date=iso",
                "--pretty=format:%h%x09%ad%x09%an%x09%s",
            ],
            path,
            allow_failure=True,
        )

    def branch(self, project: str, path: str = "") -> dict[str, Any]:
        return self._run_git(
            project,
            ["branch", "--list", "--verbose"],
            path,
            allow_failure=True,
        )

    def current_branch(self, project: str, path: str = "") -> dict[str, Any]:
        return self._run_git(
            project,
            ["branch", "--show-current"],
            path,
            allow_failure=True,
        )

    def init(self, project: str, path: str = "") -> dict[str, Any]:
        return self._run_git(project, ["init"], path, detect_repo=False)

    def add(
        self,
        project: str,
        paths: list[str],
        path: str = "",
    ) -> dict[str, Any]:
        relative_paths = self._resolve_relative_paths(project, paths, path)
        if not relative_paths:
            raise ValueError(
                "At least one path is required. Use ['.'] only when you "
                "intentionally want to stage everything."
            )
        return self._run_git(project, ["add", "--", *relative_paths], path)

    def unstage(
        self,
        project: str,
        paths: list[str],
        path: str = "",
    ) -> dict[str, Any]:
        relative_paths = self._resolve_relative_paths(project, paths, path)
        if not relative_paths:
            raise ValueError("At least one path is required.")
        return self._run_git(
            project,
            ["restore", "--staged", "--", *relative_paths],
            path,
            allow_failure=True,
        )

    def commit(
        self,
        project: str,
        message: str,
        paths: list[str] | None = None,
        path: str = "",
    ) -> dict[str, Any]:
        if not message.strip():
            raise ValueError("Commit message is required")

        results: list[dict[str, Any]] = []
        if paths:
            results.append(self.add(project, paths, path))
        commit_result = self._run_git(
            project,
            ["commit", "-m", message.strip()],
            path,
            allow_failure=True,
        )
        results.append(commit_result)
        return {
            "project": project,
            "path": path,
            "steps": results,
            "ok": all(step.get("ok") for step in results),
        }

    def create_branch(
        self,
        project: str,
        branch_name: str,
        checkout: bool = True,
        path: str = "",
    ) -> dict[str, Any]:
        if not branch_name.strip():
            raise ValueError("Branch name is required")
        args = (
            ["checkout", "-b", branch_name.strip()]
            if checkout
            else ["branch", branch_name.strip()]
        )
        return self._run_git(project, args, path)

    def checkout(
        self,
        project: str,
        branch_name: str,
        path: str = "",
    ) -> dict[str, Any]:
        if not branch_name.strip():
            raise ValueError("Branch name is required")
        return self._run_git(
            project,
            ["checkout", branch_name.strip()],
            path,
        )
