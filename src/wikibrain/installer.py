from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import BrainConfig, atomic_write_text, ensure_private_directory


CLIENTS = {"claude", "codex"}
EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "PostCompact")
HOOK_SHIM_NAME = "wikibrain-hook"
WINDOWS_HOOK_SHIM_NAME = "wikibrain-hook.ps1"
EXECUTABLE_FILE_MODE = 0o700


def default_client_path(client: str) -> Path:
    if client == "claude":
        return Path.home() / ".claude" / "settings.json"
    if client == "codex":
        return Path.home() / ".codex" / "hooks.json"
    raise ValueError(f"unsupported client: {client}")


def resolve_brainctl(command: str | None = None) -> str:
    selected = command or shutil.which("brainctl")
    if not selected:
        invoked = Path(sys.argv[0]).expanduser()
        if invoked.stem == "brainctl" and invoked.exists():
            selected = os.path.abspath(str(invoked))
    if not selected:
        raise FileNotFoundError(
            "brainctl is not on PATH; pass --command with its absolute path"
        )
    path = Path(selected).expanduser()
    if (
        path.exists()
        or path.is_absolute()
        or "/" in selected
        or "\\" in selected
    ):
        # Keep a stable, user-facing symlink such as /opt/homebrew/bin/brainctl.
        # Resolving it would pin the shim to a versioned Homebrew Cellar path.
        return os.path.abspath(str(path))
    return selected


def _shim_path(config: BrainConfig) -> Path:
    name = WINDOWS_HOOK_SHIM_NAME if os.name == "nt" else HOOK_SHIM_NAME
    return config.home_path / "bin" / name


def _posix_shim_content(executable: str) -> str:
    quoted = shlex.quote(executable)
    executable_path = Path(executable).expanduser()
    path_setup = ""
    if executable_path.is_absolute() or len(executable_path.parts) > 1:
        # GUI-launched agents may not inherit Homebrew's bin directory. Keep
        # sibling tools such as the linked `wikimap` command discoverable
        # without pinning either executable to a versioned Cellar path.
        executable_directory = shlex.quote(str(executable_path.parent))
        path_setup = (
            f"PATH={executable_directory}${{PATH:+:$PATH}}\n"
            "export PATH\n"
        )
    return (
        "#!/bin/sh\n"
        "\n"
        "# wikibrain-managed-hook:v1\n"
        f"# wikibrain-target-json:{json.dumps(executable)}\n"
        f"{path_setup}"
        f"if command -v {quoted} >/dev/null 2>&1; then\n"
        f"  exec {quoted} \"$@\"\n"
        "fi\n"
        "\n"
        "printf '{}\\n'\n"
        "exit 0\n"
    )


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _windows_shim_content(executable: str) -> str:
    target = _powershell_literal(executable)
    return (
        "# wikibrain-managed-hook:v1\n"
        f"# wikibrain-target-json:{json.dumps(executable)}\n"
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        f"$target = {target}\n"
        "$resolved = $null\n"
        "if ([System.IO.Path]::IsPathRooted($target)) {\n"
        "  if (Test-Path -LiteralPath $target -PathType Leaf) {\n"
        "    $resolved = $target\n"
        "  }\n"
        "} else {\n"
        "  $found = Get-Command -Name $target -CommandType Application "
        "-ErrorAction SilentlyContinue | Select-Object -First 1\n"
        "  if ($null -ne $found) {\n"
        "    $resolved = $found.Source\n"
        "  }\n"
        "}\n"
        "if ($null -ne $resolved) {\n"
        "  $parent = Split-Path -LiteralPath $resolved -Parent\n"
        "  if ($parent) {\n"
        "    $env:PATH = \"$parent;$env:PATH\"\n"
        "  }\n"
        "  & $resolved @args\n"
        "  if ($null -eq $LASTEXITCODE) {\n"
        "    exit 0\n"
        "  }\n"
        "  exit $LASTEXITCODE\n"
        "}\n"
        "[Console]::Out.WriteLine('{}')\n"
        "exit 0\n"
    )


def _shim_content(executable: str) -> str:
    if os.name == "nt":
        return _windows_shim_content(executable)
    return _posix_shim_content(executable)


def _install_shim(config: BrainConfig, executable: str) -> Path:
    path = _shim_path(config)
    atomic_write_text(
        path,
        _shim_content(executable),
        mode=EXECUTABLE_FILE_MODE,
    )
    return path


def _windows_command(command: str, client: str) -> str:
    return (
        "powershell.exe -NoLogo -NoProfile -NonInteractive "
        f'-ExecutionPolicy Bypass -File "{command}" '
        f"hook --provider {client}"
    )


def _handler(command: str, client: str, event: str) -> dict[str, Any]:
    if event in {"Stop", "PostCompact"}:
        timeout = 20
    elif event == "UserPromptSubmit":
        timeout = 8
    else:
        timeout = 5
    if command.casefold().endswith(".ps1"):
        if client == "claude":
            handler = {
                "type": "command",
                "command": "powershell.exe",
                "args": [
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    command,
                    "hook",
                    "--provider",
                    client,
                ],
                "timeout": timeout,
            }
        else:
            windows_command = _windows_command(command, client)
            handler = {
                "type": "command",
                "command": windows_command,
                "commandWindows": windows_command,
                "timeout": timeout,
            }
    else:
        handler = {
            "type": "command",
            "command": f"{shlex.quote(command)} hook --provider {client}",
            "timeout": timeout,
        }
    if event == "SessionStart":
        handler["statusMessage"] = "WikiBrain: recalling local memory"
    return handler


def hook_group(command: str, client: str, event: str) -> dict[str, Any]:
    group: dict[str, Any] = {"hooks": [_handler(command, client, event)]}
    if event == "SessionStart":
        group["matcher"] = "startup|resume|clear|compact"
    elif event == "PostToolUse":
        group["matcher"] = "Bash|Edit|Write|NotebookEdit|apply_patch"
    elif event == "PostCompact":
        group["matcher"] = "manual|auto"
    return group


def _command_basename(command: str) -> str:
    return command.strip("\"'").replace("\\", "/").rsplit("/", 1)[-1]


def _owned_executable(handler: Any, client: str) -> str | None:
    if not isinstance(handler, dict):
        return None
    arguments = handler.get("args")
    command = handler.get("command")
    if isinstance(arguments, list) and all(
        isinstance(value, str) for value in arguments
    ):
        if not isinstance(command, str):
            return None
        if (
            _command_basename(command).casefold()
            not in {"powershell.exe", "pwsh.exe"}
            or arguments[-3:] != ["hook", "--provider", client]
        ):
            return None
        file_indexes = [
            index
            for index, value in enumerate(arguments)
            if value.casefold() == "-file"
        ]
        if not file_indexes:
            return None
        index = file_indexes[-1]
        if index + 1 >= len(arguments):
            return None
        executable = arguments[index + 1]
        return (
            executable
            if _command_basename(executable).casefold()
            in {WINDOWS_HOOK_SHIM_NAME, "brainctl.exe", "brainctl"}
            else None
        )

    windows_command = handler.get("commandWindows")
    if isinstance(windows_command, str) and windows_command:
        command = windows_command
    if not isinstance(command, str):
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if len(parts) < 4 or parts[-3:] != ["hook", "--provider", client]:
        return None
    first_name = _command_basename(parts[0]).casefold()
    if first_name in {"powershell.exe", "pwsh.exe"}:
        file_indexes = [
            index
            for index, value in enumerate(parts)
            if value.casefold() == "-file"
        ]
        if not file_indexes:
            return None
        index = file_indexes[-1]
        if index + 1 >= len(parts):
            return None
        executable = parts[index + 1]
    else:
        executable = parts[0]
    executable_name = _command_basename(executable).casefold()
    if executable_name in {
        HOOK_SHIM_NAME,
        WINDOWS_HOOK_SHIM_NAME,
        "brainctl",
        "brainctl.exe",
        "brainctl.cmd",
    }:
        return executable
    return None


def _is_owned_handler(handler: Any, client: str) -> bool:
    return _owned_executable(handler, client) is not None


def _handler_executable(handler: Any, client: str) -> str | None:
    return _owned_executable(handler, client)


def _command_is_executable(command: str) -> bool:
    if "/" not in command and "\\" not in command:
        selected = shutil.which(command)
        return selected is not None and (
            os.name == "nt" or os.access(selected, os.X_OK)
        )
    path = Path(command).expanduser()
    return path.is_file() and (
        os.name == "nt" or os.access(path, os.X_OK)
    )


def _managed_shim_target(command: str) -> str | None:
    path = Path(command).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if "# wikibrain-managed-hook:v1" not in text:
        return None
    prefix = "# wikibrain-target-json:"
    for line in text.splitlines():
        if not line.startswith(prefix):
            continue
        try:
            target = json.loads(line.removeprefix(prefix))
        except json.JSONDecodeError:
            return None
        return target if isinstance(target, str) and target else None
    return None


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.wikibrain.{stamp}.bak")
    ensure_private_directory(backup.parent)
    shutil.copy2(path, backup)
    return backup


def _merge(payload: dict[str, Any], client: str, command: str) -> tuple[dict[str, Any], int]:
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings field 'hooks' must be an object")
    changes = 0
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"settings hooks.{event} must be an array")
        desired = hook_group(command, client, event)
        owned_count = sum(
            _is_owned_handler(handler, client)
            for group in groups
            if isinstance(group, dict) and isinstance(group.get("hooks"), list)
            for handler in group["hooks"]
        )
        if owned_count == 1 and any(group == desired for group in groups):
            continue

        kept_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)
                continue
            kept_handlers = [
                handler
                for handler in group["hooks"]
                if not _is_owned_handler(handler, client)
            ]
            if kept_handlers:
                updated = dict(group)
                updated["hooks"] = kept_handlers
                kept_groups.append(updated)
        kept_groups.append(desired)
        hooks[event] = kept_groups
        changes += 1
    return payload, changes


def _remove(payload: dict[str, Any], client: str) -> tuple[dict[str, Any], int]:
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return payload, 0
    changes = 0
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)
                continue
            handlers = group["hooks"]
            kept_handlers = [
                handler
                for handler in handlers
                if not _is_owned_handler(handler, client)
            ]
            changes += len(handlers) - len(kept_handlers)
            if kept_handlers:
                updated = dict(group)
                updated["hooks"] = kept_handlers
                kept_groups.append(updated)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        payload.pop("hooks", None)
    return payload, changes


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(
        path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )


def install_hooks(
    config: BrainConfig,
    clients: list[str],
    *,
    command: str | None = None,
    paths: dict[str, Path] | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    unsupported = [client for client in clients if client not in CLIENTS]
    if unsupported:
        raise ValueError(f"unsupported client: {unsupported[0]}")
    executable = resolve_brainctl(command)
    shim = _shim_path(config)
    if not dry_run:
        _install_shim(config, executable)
    hook_command = str(shim)
    results: list[dict[str, Any]] = []
    ledger_path = config.home_path / "installations.json"
    ledger: dict[str, Any] = _load(ledger_path) if ledger_path.exists() else {}
    installations = ledger.setdefault("clients", {})
    for client in clients:
        if client not in CLIENTS:
            raise ValueError(f"unsupported client: {client}")
        path = (paths or {}).get(
            client, default_client_path(client)
        ).expanduser().resolve()
        payload = _load(path)
        merged, changes = _merge(payload, client, hook_command)
        backup = None
        if changes and not dry_run:
            backup = _backup(path)
            _write_json(path, merged)
        if not dry_run:
            installations[client] = {
                "path": str(path),
                "command": executable,
                "hook_command": hook_command,
                "installed_at": datetime.now(UTC).isoformat(),
                "backup": str(backup) if backup else None,
            }
        results.append(
            {
                "client": client,
                "path": str(path),
                "changes": changes,
                "backup": str(backup) if backup else None,
                "dry_run": dry_run,
                "hook_command": hook_command,
            }
        )
    if not dry_run:
        _write_json(ledger_path, ledger)
    return results


def uninstall_hooks(
    config: BrainConfig,
    clients: list[str],
    *,
    paths: dict[str, Path] | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for client in clients:
        if client not in CLIENTS:
            raise ValueError(f"unsupported client: {client}")
        path = (paths or {}).get(
            client, default_client_path(client)
        ).expanduser().resolve()
        payload = _load(path)
        updated, changes = _remove(payload, client)
        backup = None
        if changes and not dry_run:
            backup = _backup(path)
            _write_json(path, updated)
        results.append(
            {
                "client": client,
                "path": str(path),
                "changes": changes,
                "backup": str(backup) if backup else None,
                "dry_run": dry_run,
            }
        )
    if not dry_run:
        ledger_path = config.home_path / "installations.json"
        if ledger_path.exists():
            ledger = _load(ledger_path)
            installations = ledger.get("clients")
            if isinstance(installations, dict):
                for client in clients:
                    installations.pop(client, None)
                _write_json(ledger_path, ledger)
    return results


def configured_hook_status(config: BrainConfig) -> list[dict[str, Any]]:
    ledger_path = config.home_path / "installations.json"
    if not ledger_path.exists():
        return hook_status()
    try:
        ledger = _load(ledger_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return hook_status()
    installations = ledger.get("clients")
    if not isinstance(installations, dict):
        return hook_status()
    clients: list[str] = []
    paths: dict[str, Path] = {}
    for client in sorted(CLIENTS):
        installation = installations.get(client)
        if not isinstance(installation, dict):
            continue
        path = installation.get("path")
        if not isinstance(path, str) or not path:
            continue
        clients.append(client)
        paths[client] = Path(path).expanduser().resolve()
    return hook_status(paths, clients=clients) if clients else hook_status()


def hook_status(
    paths: dict[str, Path] | None = None,
    *,
    clients: list[str] | None = None,
) -> list[dict[str, Any]]:
    selected_clients = sorted(CLIENTS if clients is None else clients)
    unsupported = [client for client in selected_clients if client not in CLIENTS]
    if unsupported:
        raise ValueError(f"unsupported client: {unsupported[0]}")
    statuses: list[dict[str, Any]] = []
    for client in selected_clients:
        path = (paths or {}).get(
            client, default_client_path(client)
        ).expanduser().resolve()
        try:
            payload = _load(path)
            hooks = payload.get("hooks", {})
            count = 0
            desired = True
            executables: list[str] = []
            issues: list[str] = []
            if isinstance(hooks, dict):
                for event in EVENTS:
                    groups = hooks.get(event, [])
                    if not isinstance(groups, list):
                        desired = False
                        issues.append(f"hooks.{event} is not an array")
                        continue
                    event_handlers: list[Any] = []
                    for group in groups:
                        if not isinstance(group, dict):
                            continue
                        handlers = group.get("hooks")
                        if isinstance(handlers, list):
                            event_handlers.extend(
                                handler
                                for handler in handlers
                                if _is_owned_handler(handler, client)
                            )
                    count += len(event_handlers)
                    if len(event_handlers) != 1:
                        desired = False
                        issues.append(
                            f"{event}: expected 1 WikiBrain hook, found "
                            f"{len(event_handlers)}"
                        )
                        continue
                    executable = _handler_executable(event_handlers[0], client)
                    if executable is None:
                        desired = False
                        issues.append(f"{event}: command could not be parsed")
                        continue
                    executables.append(executable)
                    if _command_basename(executable).casefold() not in {
                        HOOK_SHIM_NAME,
                        WINDOWS_HOOK_SHIM_NAME,
                    }:
                        desired = False
                        issues.append(f"{event}: persistent shim is not in use")
                    expected_group = hook_group(executable, client, event)
                    if not any(group == expected_group for group in groups):
                        desired = False
                        issues.append(f"{event}: definition is stale")
            else:
                desired = False
                issues.append("settings field 'hooks' is not an object")
            unique_executables = sorted(set(executables))
            if len(unique_executables) > 1:
                desired = False
                issues.append("WikiBrain hooks use inconsistent executables")
            executable_ok = bool(unique_executables) and all(
                _command_is_executable(command) for command in unique_executables
            )
            if unique_executables and not executable_ok:
                issues.append("WikiBrain hook shim is missing or not executable")
            if executable_ok:
                targets = [
                    _managed_shim_target(command)
                    for command in unique_executables
                ]
                if not all(
                    target is not None and _command_is_executable(target)
                    for target in targets
                ):
                    executable_ok = False
                    issues.append(
                        "WikiBrain hook target is missing or not executable"
                    )
            statuses.append(
                {
                    "client": client,
                    "path": str(path),
                    "installed_hooks": count,
                    "expected_hooks": len(EVENTS),
                    "desired": desired,
                    "executable": executable_ok,
                    "valid": desired and executable_ok,
                    "issues": issues,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            statuses.append(
                {
                    "client": client,
                    "path": str(path),
                    "installed_hooks": 0,
                    "expected_hooks": len(EVENTS),
                    "desired": False,
                    "executable": False,
                    "valid": False,
                    "issues": [str(error)],
                    "error": str(error),
                }
            )
    return statuses
