"""File-based artifact exchange shared by all workflow agents."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, cast

from contracts import CONTRACT_VERSION, ArtifactCategory, ArtifactReference


class ArtifactManager:
    """Create project workspaces and exchange immutable artifact references."""

    PROJECT_ID_PATTERN = re.compile(r"^(?P<date>\d{8})_(?P<sequence>\d{2,})$")
    CATEGORY_PATHS: dict[ArtifactCategory, Path] = {
        "image": Path("generated/images"),
        "sound": Path("generated/sounds"),
        "game": Path("game"),
        "data": Path("data"),
        "validation": Path("validation"),
    }
    PROJECT_DIRECTORIES = tuple(CATEGORY_PATHS.values())
    MANIFEST_RELATIVE_PATH = Path("data/artifact_manifest.json")
    MANIFEST_LOCK_RELATIVE_PATH = Path("data/.artifact_manifest.lock")

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        default_root = Path(__file__).resolve().parent / "workspace"
        self.workspace_root = Path(workspace_root or default_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def create_project(
        self,
        created_on: date | datetime | None = None,
        sequence: int | None = None,
    ) -> str:
        """Create and return a project ID such as ``20260926_03``.

        If ``sequence`` is omitted, the next sequence for that date is selected.
        Directory creation is exclusive, so concurrent creators cannot claim the
        same project ID.
        """

        project_date = (
            created_on.date() if isinstance(created_on, datetime) else created_on
        )
        project_date = project_date or date.today()
        prefix = project_date.strftime("%Y%m%d")

        if sequence is not None and sequence < 1:
            raise ValueError("sequence must be greater than or equal to 1")

        next_sequence = sequence or self._next_sequence(prefix)
        while True:
            project_id = f"{prefix}_{next_sequence:02d}"
            project_root = self.workspace_root / project_id
            try:
                project_root.mkdir(parents=False, exist_ok=False)
                break
            except FileExistsError:
                if sequence is not None:
                    raise FileExistsError(f"Project already exists: {project_id}")
                next_sequence += 1

        for relative_directory in self.PROJECT_DIRECTORIES:
            (project_root / relative_directory).mkdir(parents=True, exist_ok=True)

        manifest = {
            "manifest_version": "1.0.0",
            "project_id": project_id,
            "created_at": self._utc_now(),
            "artifacts": [],
        }
        self._atomic_write(
            project_root / self.MANIFEST_RELATIVE_PATH,
            self._encode_json(manifest),
            overwrite=False,
        )
        return project_id

    def ensure_project(self, project_id: str) -> Path:
        """Validate a project ID and return its existing root directory."""

        self._validate_project_id(project_id)
        project_root = (self.workspace_root / project_id).resolve()
        self._require_within(self.workspace_root, project_root)
        if not project_root.is_dir():
            raise FileNotFoundError(f"Unknown project: {project_id}")
        if not (project_root / self.MANIFEST_RELATIVE_PATH).is_file():
            raise FileNotFoundError(f"Artifact manifest is missing: {project_id}")
        return project_root

    def write_bytes(
        self,
        project_id: str,
        category: ArtifactCategory,
        filename: str | Path,
        content: bytes,
        *,
        producer: str,
        media_type: str = "application/octet-stream",
        overwrite: bool = False,
    ) -> ArtifactReference:
        """Write bytes and register an immutable, checksum-backed reference."""

        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")
        if not producer.strip():
            raise ValueError("producer must not be empty")

        project_root = self.ensure_project(project_id)
        target = self._artifact_path(project_root, category, filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(target, content, overwrite=overwrite)

        reference: ArtifactReference = {
            "contract_version": CONTRACT_VERSION,
            "artifact_id": f"{category}-{uuid.uuid4().hex}",
            "project_id": project_id,
            "category": category,
            "relative_path": target.relative_to(project_root).as_posix(),
            "media_type": media_type,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "created_at": self._utc_now(),
            "producer": producer,
        }
        self._append_manifest(reference)
        return reference

    def write_text(
        self,
        project_id: str,
        category: ArtifactCategory,
        filename: str | Path,
        content: str,
        *,
        producer: str,
        media_type: str = "text/plain; charset=utf-8",
        overwrite: bool = False,
    ) -> ArtifactReference:
        return self.write_bytes(
            project_id,
            category,
            filename,
            content.encode("utf-8"),
            producer=producer,
            media_type=media_type,
            overwrite=overwrite,
        )

    def write_json(
        self,
        project_id: str,
        category: ArtifactCategory,
        filename: str | Path,
        payload: Any,
        *,
        producer: str,
        overwrite: bool = False,
    ) -> ArtifactReference:
        return self.write_bytes(
            project_id,
            category,
            filename,
            self._encode_json(payload),
            producer=producer,
            media_type="application/json",
            overwrite=overwrite,
        )

    def import_file(
        self,
        project_id: str,
        category: ArtifactCategory,
        source: str | Path,
        *,
        producer: str,
        filename: str | Path | None = None,
        media_type: str = "application/octet-stream",
    ) -> ArtifactReference:
        """Copy an externally generated file into the managed workspace."""

        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Source artifact does not exist: {source_path}")
        return self.write_bytes(
            project_id,
            category,
            filename or source_path.name,
            source_path.read_bytes(),
            producer=producer,
            media_type=media_type,
        )

    def read_bytes(
        self,
        reference: ArtifactReference,
        *,
        verify_integrity: bool = True,
    ) -> bytes:
        """Read an artifact and optionally verify its size and SHA-256 checksum."""

        if reference["contract_version"] != CONTRACT_VERSION:
            raise ValueError(
                "Unsupported artifact contract version: "
                f"{reference['contract_version']}"
            )
        project_root = self.ensure_project(reference["project_id"])
        expected_category_root = (
            project_root / self.CATEGORY_PATHS[reference["category"]]
        ).resolve()
        target = (project_root / reference["relative_path"]).resolve()
        self._require_within(expected_category_root, target)
        if not target.is_file():
            raise FileNotFoundError(f"Artifact file does not exist: {target}")

        content = target.read_bytes()
        if verify_integrity:
            actual_hash = hashlib.sha256(content).hexdigest()
            if len(content) != reference["size_bytes"]:
                raise ValueError(f"Artifact size mismatch: {reference['artifact_id']}")
            if actual_hash != reference["sha256"]:
                raise ValueError(f"Artifact checksum mismatch: {reference['artifact_id']}")
        return content

    def read_text(
        self,
        reference: ArtifactReference,
        *,
        verify_integrity: bool = True,
    ) -> str:
        return self.read_bytes(
            reference,
            verify_integrity=verify_integrity,
        ).decode("utf-8")

    def read_json(
        self,
        reference: ArtifactReference,
        *,
        verify_integrity: bool = True,
    ) -> Any:
        return json.loads(
            self.read_text(reference, verify_integrity=verify_integrity)
        )

    def materialize(
        self,
        reference: ArtifactReference,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Copy an artifact to a tool-specific path and return that path."""

        destination_path = Path(destination).resolve()
        if destination_path.exists() and not overwrite:
            raise FileExistsError(f"Destination already exists: {destination_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.read_bytes(reference)
        self._atomic_write(destination_path, content, overwrite=overwrite)
        return destination_path

    def get_artifact(self, project_id: str, artifact_id: str) -> ArtifactReference:
        for reference in self.list_artifacts(project_id):
            if reference["artifact_id"] == artifact_id:
                return reference
        raise KeyError(f"Unknown artifact ID: {artifact_id}")

    def list_artifacts(
        self,
        project_id: str,
        category: ArtifactCategory | None = None,
    ) -> list[ArtifactReference]:
        manifest = self._read_manifest(project_id)
        artifacts = cast(list[ArtifactReference], manifest["artifacts"])
        if category is None:
            return list(artifacts)
        return [item for item in artifacts if item["category"] == category]

    def _append_manifest(self, reference: ArtifactReference) -> None:
        project_id = reference["project_id"]
        with self._manifest_lock(project_id):
            manifest = self._read_manifest(project_id)
            artifacts = cast(list[ArtifactReference], manifest["artifacts"])
            artifacts.append(reference)
            project_root = self.ensure_project(project_id)
            self._atomic_write(
                project_root / self.MANIFEST_RELATIVE_PATH,
                self._encode_json(manifest),
                overwrite=True,
            )

    def _read_manifest(self, project_id: str) -> dict[str, Any]:
        project_root = self.ensure_project(project_id)
        manifest_path = project_root / self.MANIFEST_RELATIVE_PATH
        with manifest_path.open("r", encoding="utf-8") as file:
            manifest = json.load(file)
        if manifest.get("project_id") != project_id:
            raise ValueError(f"Manifest project ID mismatch: {project_id}")
        if not isinstance(manifest.get("artifacts"), list):
            raise ValueError(f"Invalid artifact manifest: {manifest_path}")
        return cast(dict[str, Any], manifest)

    @contextmanager
    def _manifest_lock(
        self,
        project_id: str,
        timeout_seconds: float = 10.0,
    ) -> Iterator[None]:
        project_root = self.ensure_project(project_id)
        lock_path = project_root / self.MANIFEST_LOCK_RELATIVE_PATH
        deadline = time.monotonic() + timeout_seconds
        file_descriptor: int | None = None

        while file_descriptor is None:
            try:
                file_descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(file_descriptor, str(os.getpid()).encode("ascii"))
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for artifact manifest: {project_id}"
                    )
                time.sleep(0.05)

        try:
            yield
        finally:
            os.close(file_descriptor)
            lock_path.unlink(missing_ok=True)

    def _artifact_path(
        self,
        project_root: Path,
        category: ArtifactCategory,
        filename: str | Path,
    ) -> Path:
        if category not in self.CATEGORY_PATHS:
            raise ValueError(f"Unsupported artifact category: {category}")
        relative_name = Path(filename)
        if relative_name.is_absolute() or ".." in relative_name.parts:
            raise ValueError(f"Artifact filename must be a safe relative path: {filename}")
        if not relative_name.name:
            raise ValueError("Artifact filename must not be empty")

        category_root = (project_root / self.CATEGORY_PATHS[category]).resolve()
        target = (category_root / relative_name).resolve()
        self._require_within(category_root, target)
        return target

    def _next_sequence(self, date_prefix: str) -> int:
        sequences = []
        for path in self.workspace_root.glob(f"{date_prefix}_*"):
            match = self.PROJECT_ID_PATTERN.fullmatch(path.name)
            if match:
                sequences.append(int(match.group("sequence")))
        return max(sequences, default=0) + 1

    def _validate_project_id(self, project_id: str) -> None:
        if not self.PROJECT_ID_PATTERN.fullmatch(project_id):
            raise ValueError(
                "project_id must use YYYYMMDD_NN format, for example 20260926_03"
            )

    @staticmethod
    def _require_within(parent: Path, child: Path) -> None:
        try:
            child.relative_to(parent)
        except ValueError as error:
            raise ValueError(f"Path escapes managed workspace: {child}") from error

    @staticmethod
    def _encode_json(payload: Any) -> bytes:
        return (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

    @staticmethod
    def _atomic_write(target: Path, content: bytes, *, overwrite: bool) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Artifact already exists: {target}")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            if overwrite:
                os.replace(temporary_path, target)
            else:
                # A hard link publishes the completed temp file atomically and
                # fails if another writer already claimed the destination.
                os.link(temporary_path, target)
                temporary_path.unlink()
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
