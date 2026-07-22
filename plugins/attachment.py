from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from mcp_platform.context import PlatformContext


_DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
_COPY_BUFFER_BYTES = 1024 * 1024


class AttachmentPlugin:
    """Save locally available attachments into a configured destination folder."""

    name = "attachment"
    description = "Save local attachment files into a configured destination folder."

    def register_tools(self, mcp: Any, context: PlatformContext) -> None:
        settings = context.config_service.get_settings()
        configured_root = settings.get(
            "attachment_save_directory",
            r"D:\07庫電腦D槽-214585\214585\C342\History",
        )
        configured_source_root = settings.get(
            "attachment_source_directory",
            r"D:\AIProjects\A16-mcp-relay\company-agent\attachments",
        )
        max_bytes = int(settings.get("max_attachment_bytes", _DEFAULT_MAX_BYTES))
        allowed_root = Path(str(configured_root)).expanduser().resolve()
        source_root = Path(str(configured_source_root)).expanduser().resolve()

        @mcp.tool()
        def attachment_save_file(
            source_path: str,
            filename: str = "",
            subfolder: str = "",
            overwrite: bool = False,
            delete_source: bool = False,
        ) -> dict[str, Any]:
            """Save an attachment from the configured local source folder.

            The source must be a regular file inside ``attachment_source_directory``.
            The destination remains inside ``attachment_save_directory``. Any file type
            is accepted up to the configured size limit.
            """

            try:
                return self._save_file(
                    allowed_root=allowed_root,
                    source_root=source_root,
                    max_bytes=max_bytes,
                    source_path=source_path,
                    filename=filename,
                    subfolder=subfolder,
                    overwrite=overwrite,
                    delete_source=delete_source,
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "error": str(exc),
                    "source_root": str(source_root),
                    "allowed_root": str(allowed_root),
                }

        @mcp.tool()
        def attachment_storage_info() -> dict[str, Any]:
            """Return configured attachment source, destination, and size limit."""

            return {
                "ok": True,
                "source_directory": str(source_root),
                "source_exists": source_root.exists(),
                "destination_directory": str(allowed_root),
                "destination_exists": allowed_root.exists(),
                "max_attachment_bytes": max_bytes,
                "max_attachment_gib": round(max_bytes / (1024**3), 3),
                "file_types": "all",
                "transfer_method": "local_file",
            }

    def _save_file(
        self,
        *,
        allowed_root: Path,
        source_root: Path,
        max_bytes: int,
        source_path: str,
        filename: str,
        subfolder: str,
        overwrite: bool,
        delete_source: bool,
    ) -> dict[str, Any]:
        source_text = source_path.strip().strip('"').strip("'")
        if not source_text:
            raise ValueError("source_path is required.")

        supplied_source = Path(source_text).expanduser()
        source = (
            supplied_source.resolve()
            if supplied_source.is_absolute()
            else (source_root / supplied_source).resolve()
        )
        self._require_inside_root(source_root, source, label="source")

        if source.is_symlink():
            raise PermissionError("Symbolic-link attachment sources are not allowed.")
        if not source.is_file():
            raise FileNotFoundError(f"Attachment source file was not found: {source}")

        source_size = source.stat().st_size
        if source_size <= 0:
            raise ValueError("The attachment is empty.")
        if source_size > max_bytes:
            raise ValueError(
                f"Attachment is too large: {source_size} bytes. Limit: {max_bytes} bytes."
            )

        requested_name = filename.strip().strip('"').strip("'")
        clean_name = Path(requested_name).name if requested_name else source.name
        if not clean_name or clean_name in {".", ".."}:
            raise ValueError("A valid destination filename is required.")

        relative_folder = subfolder.strip().strip('"').strip("'")
        destination_dir = (allowed_root / relative_folder).resolve()
        self._require_inside_root(allowed_root, destination_dir, label="destination")
        destination = (destination_dir / clean_name).resolve()
        self._require_inside_root(allowed_root, destination, label="destination")

        if os.path.normcase(str(source)) == os.path.normcase(str(destination)):
            raise ValueError("Source and destination must be different files.")
        if destination.exists() and not overwrite:
            raise FileExistsError(
                "Destination already exists. Set overwrite=true to replace it: "
                f"{destination}"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.part")
        if temporary.exists():
            temporary.unlink()

        digest = hashlib.sha256()
        copied_bytes = 0
        try:
            with source.open("rb") as source_stream, temporary.open("xb") as target_stream:
                copied_bytes = self._copy_and_hash(source_stream, target_stream, digest)
            if copied_bytes != source_size:
                raise OSError(
                    f"Attachment copy was incomplete: expected {source_size}, copied {copied_bytes}."
                )
            os.replace(temporary, destination)
            shutil.copystat(source, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        if delete_source:
            source.unlink()

        mime_type, _ = mimetypes.guess_type(destination.name)
        return {
            "ok": True,
            "path": str(destination),
            "filename": destination.name,
            "size_bytes": copied_bytes,
            "mime_type": mime_type,
            "sha256": digest.hexdigest(),
            "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "overwritten": overwrite,
            "source_deleted": delete_source,
            "source_kind": "local_file",
        }

    @staticmethod
    def _copy_and_hash(
        source_stream: BinaryIO,
        target_stream: BinaryIO,
        digest: Any,
    ) -> int:
        copied = 0
        while True:
            chunk = source_stream.read(_COPY_BUFFER_BYTES)
            if not chunk:
                return copied
            target_stream.write(chunk)
            digest.update(chunk)
            copied += len(chunk)

    @staticmethod
    def _require_inside_root(root: Path, path: Path, *, label: str) -> None:
        root_text = os.path.normcase(os.path.realpath(os.path.abspath(str(root))))
        path_text = os.path.normcase(os.path.realpath(os.path.abspath(str(path))))
        try:
            common = os.path.commonpath([root_text, path_text])
        except ValueError as exc:
            raise PermissionError(f"Invalid {label} path: {exc}") from exc
        if os.path.normcase(common) != root_text:
            raise PermissionError(f"{label.title()} must remain inside: {root}")


def create_plugin() -> AttachmentPlugin:
    return AttachmentPlugin()
