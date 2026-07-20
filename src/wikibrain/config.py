from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


APP_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
CONFIG_VERSION = 1


def default_home() -> Path:
    override = os.environ.get("WIKIBRAIN_HOME")
    if override:
        return Path(override).expanduser().resolve()
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return (Path(data_home).expanduser() / "wikibrain").resolve()
    return (Path.home() / ".local" / "share" / "wikibrain").resolve()


def default_workspace() -> Path:
    """Return the zero-configuration capture root for the current user."""
    return Path.home().expanduser().resolve()


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(APP_DIR_MODE)
    except OSError:
        pass


def atomic_write_text(path: Path, content: str, mode: int = PRIVATE_FILE_MODE) -> None:
    ensure_private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


@dataclass(slots=True)
class BrainConfig:
    version: int
    home: str
    vault: str
    workspace_roots: list[str]
    paused: bool = False
    archive_retention_days: int = 90
    max_input_bytes: int = 1_048_576
    max_field_chars: int = 40_000
    recall_char_limit: int = 6_000
    recall_result_limit: int = 6
    wikimap_command: str = "wikimap"
    update_on_stop: bool = True

    @property
    def home_path(self) -> Path:
        return Path(self.home)

    @property
    def vault_path(self) -> Path:
        return Path(self.vault)

    @property
    def database_path(self) -> Path:
        return self.home_path / "state.db"

    @property
    def config_path(self) -> Path:
        return self.home_path / "config.json"

    @property
    def log_path(self) -> Path:
        return self.home_path / "logs" / "wikibrain.log"

    def allows(self, cwd: str) -> bool:
        if self.paused:
            return False
        return self.scope_for(cwd) is not None

    def scope_for(self, cwd: str) -> Path | None:
        """Return a stable project scope inside the configured allowlist."""
        try:
            candidate = Path(cwd).expanduser().resolve()
        except (OSError, RuntimeError):
            return None
        matching_roots: list[Path] = []
        for root_value in self.workspace_roots:
            try:
                root = Path(root_value).expanduser().resolve()
                candidate.relative_to(root)
                matching_roots.append(root)
            except (OSError, RuntimeError, ValueError):
                continue
        if not matching_roots:
            return None
        allowed_root = max(matching_roots, key=lambda path: len(path.parts))
        current = candidate if candidate.is_dir() else candidate.parent
        while True:
            if (current / ".git").exists():
                return current
            if current == allowed_root:
                return allowed_root
            if allowed_root not in current.parents:
                return allowed_root
            current = current.parent

    def save(self) -> None:
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(self.config_path, payload)

    @classmethod
    def create(
        cls,
        home: Path,
        vault: Path | None = None,
        workspace_roots: list[Path] | None = None,
    ) -> "BrainConfig":
        home = home.expanduser().resolve()
        vault = (vault or (home / "vault")).expanduser().resolve()
        roots = workspace_roots or [default_workspace()]
        config = cls(
            version=CONFIG_VERSION,
            home=str(home),
            vault=str(vault),
            workspace_roots=[str(path.expanduser().resolve()) for path in roots],
        )
        for directory in (home, vault, home / "logs", home / "receipts"):
            ensure_private_directory(directory)
        config.save()
        return config

    @classmethod
    def load(cls, home: Path | None = None) -> "BrainConfig":
        selected_home = (home or default_home()).expanduser().resolve()
        path = selected_home / "config.json"
        with path.open(encoding="utf-8") as handle:
            payload: dict[str, Any] = json.load(handle)
        payload["home"] = str(selected_home)
        return cls(**payload)


def file_mode(path: Path) -> str:
    return stat.filemode(path.stat().st_mode)
