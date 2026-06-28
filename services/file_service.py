from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any, Iterable

from services.config_service import ConfigService


class FileService:
    def __init__(self, config_service: ConfigService) -> None:
        self.config_service = config_service

    def get_project_root(self, project: str) -> Path:
        projects = self.config_service.get_projects()
        if project not in projects:
            available = ", ".join(sorted(projects.keys()))
            raise ValueError(f"Unknown project '{project}'. Available projects: {available}")
        root = Path(projects[project]).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Project root does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Project root is not a directory: {root}")
        return root

    def resolve_project_path(self, project: str, relative_path: str = "") -> Path:
        root = self.get_project_root(project)
        candidate = (root / (relative_path or "")).resolve()
        root_text = os.path.normcase(str(root))
        candidate_text = os.path.normcase(str(candidate))
        if os.path.commonpath([root_text, candidate_text]) != root_text:
            raise PermissionError(f"Access denied. Path escapes project root. project={project}, path={relative_path}")
        return candidate

    def ensure_writable_path(self, path: Path) -> None:
        allowed = self.config_service.get_allowed_write_extensions()
        if allowed and path.suffix.lower() not in allowed:
            raise PermissionError(f"Writes to '*{path.suffix.lower()}' files are not allowed. Allowed extensions: {sorted(allowed)}")

    def format_file_entry(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "name": path.name,
            "type": "directory" if path.is_dir() else "file",
            "size": stat.st_size if path.is_file() else None,
            "modified": stat.st_mtime,
        }

    def should_exclude(self, path: Path, patterns: Iterable[str]) -> bool:
        text = path.as_posix()
        return any(fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(text, pattern) for pattern in patterns)

    def relative_to_project(self, project: str, path: Path) -> str:
        return str(path.relative_to(self.get_project_root(project))).replace("\\", "/")

    def list_projects(self) -> dict[str, Any]:
        projects = self.config_service.get_projects()
        return {
            "projects": [
                {"name": name, "root": str(Path(root).resolve()), "exists": Path(root).exists()}
                for name, root in sorted(projects.items())
            ]
        }

    def list_files(self, project: str, path: str = "") -> dict[str, Any]:
        target = self.resolve_project_path(project, path)
        if not target.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        return {"project": project, "path": path, "absolute_path": str(target), "entries": [self.format_file_entry(entry) for entry in entries]}

    def read_file(self, project: str, path: str) -> dict[str, Any]:
        target = self.resolve_project_path(project, path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not target.is_file():
            raise IsADirectoryError(f"Not a file: {path}")
        size = target.stat().st_size
        max_read_bytes = self.config_service.get_max_read_bytes()
        if size > max_read_bytes:
            raise ValueError(f"File is too large to read safely: {size} bytes. Limit: {max_read_bytes} bytes")
        return {"project": project, "path": path, "absolute_path": str(target), "size": size, "content": target.read_text(encoding="utf-8")}

    def read_multiple_files(self, project: str, paths: list[str]) -> dict[str, Any]:
        results = []
        for path in paths:
            try:
                results.append({"path": path, "ok": True, "file": self.read_file(project, path)})
            except Exception as exc:
                results.append({"path": path, "ok": False, "error": str(exc)})
        return {"project": project, "results": results}

    def write_file(self, project: str, path: str, content: str) -> dict[str, Any]:
        target = self.resolve_project_path(project, path)
        self.ensure_writable_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"project": project, "path": path, "absolute_path": str(target), "bytes_written": target.stat().st_size, "status": "written"}

    def append_file(self, project: str, path: str, content: str) -> dict[str, Any]:
        target = self.resolve_project_path(project, path)
        self.ensure_writable_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="") as f:
            f.write(content)
        return {"project": project, "path": path, "absolute_path": str(target), "bytes_total": target.stat().st_size, "status": "appended"}

    def iter_project_files(self, project: str, path: str = "", exclude_patterns: list[str] | None = None):
        root = self.resolve_project_path(project, path)
        if root.is_file():
            yield root
            return
        patterns = self.config_service.get_default_exclude_patterns()
        if exclude_patterns:
            patterns.extend(exclude_patterns)
        stack = [root]
        while stack:
            current = stack.pop()
            for item in sorted(current.iterdir(), key=lambda p: p.name.lower(), reverse=True):
                if self.should_exclude(item, patterns):
                    continue
                if item.is_dir():
                    stack.append(item)
                elif item.is_file():
                    yield item

    def search_files(self, project: str, pattern: str, path: str = "", exclude_patterns: list[str] | None = None, max_results: int = 200) -> dict[str, Any]:
        matches = []
        for file_path in self.iter_project_files(project, path, exclude_patterns):
            relative = self.relative_to_project(project, file_path)
            if fnmatch.fnmatch(file_path.name, pattern) or fnmatch.fnmatch(relative, pattern):
                matches.append({"path": relative, "size": file_path.stat().st_size, "modified": file_path.stat().st_mtime})
                if len(matches) >= max_results:
                    break
        return {"project": project, "pattern": pattern, "matches": matches, "truncated": len(matches) >= max_results}

    def grep_text(self, project: str, query: str, path: str = "", include_patterns: list[str] | None = None, exclude_patterns: list[str] | None = None, case_sensitive: bool = False, max_results: int = 100) -> dict[str, Any]:
        results = []
        needle = query if case_sensitive else query.lower()
        include_patterns = include_patterns or ["*.py", "*.md", "*.json", "*.txt", "*.js", "*.ts", "*.html", "*.css", "*.cs", "*.csproj", "*.sln"]
        for file_path in self.iter_project_files(project, path, exclude_patterns):
            relative = self.relative_to_project(project, file_path)
            if not any(fnmatch.fnmatch(file_path.name, p) or fnmatch.fnmatch(relative, p) for p in include_patterns):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(lines, start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    results.append({"path": relative, "line": line_no, "text": line})
                    if len(results) >= max_results:
                        return {"project": project, "query": query, "matches": results, "truncated": True}
        return {"project": project, "query": query, "matches": results, "truncated": False}

    def replace_text(self, project: str, path: str, old_text: str, new_text: str, dry_run: bool = True) -> dict[str, Any]:
        target = self.resolve_project_path(project, path)
        self.ensure_writable_path(target)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not target.is_file():
            raise IsADirectoryError(f"Not a file: {path}")
        content = target.read_text(encoding="utf-8")
        count = content.count(old_text)
        updated = content.replace(old_text, new_text)
        if not dry_run and count > 0:
            target.write_text(updated, encoding="utf-8")
        return {"project": project, "path": path, "matches": count, "dry_run": dry_run, "status": "preview" if dry_run else "written"}

    def project_tree(self, project: str, path: str = "", max_depth: int = 3, exclude_patterns: list[str] | None = None) -> dict[str, Any]:
        root = self.resolve_project_path(project, path)
        patterns = self.config_service.get_default_exclude_patterns()
        if exclude_patterns:
            patterns.extend(exclude_patterns)

        def build_node(current: Path, depth: int) -> dict[str, Any]:
            node = {"name": current.name or str(current), "type": "directory" if current.is_dir() else "file"}
            if current.is_file():
                node["size"] = current.stat().st_size
                return node
            if depth >= max_depth:
                node["children"] = []
                node["truncated"] = True
                return node
            children = []
            for child in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if self.should_exclude(child, patterns):
                    continue
                children.append(build_node(child, depth + 1))
            node["children"] = children
            return node

        return {"project": project, "path": path, "absolute_path": str(root), "tree": build_node(root, 0)}
