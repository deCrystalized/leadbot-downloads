"""Own a single planned worker replacement and reconcile its durable receipts."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

WorkerState = Literal["original", "candidate", "restored", "foreign", "unavailable"]
Health = Literal["healthy", "starting", "confirmed_failure", "unavailable"]
CommandResult = Literal["completed", "failed", "uncertain"]


@dataclass(frozen=True)
class Worker:
    state: WorkerState
    health: Health
    container_id: str | None


def process_birth(pid: int, proc: Path = Path("/proc")) -> str | None:
    """A PID alone is insufficient to establish whether a Linux owner is still live."""
    try:
        fields = (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (OSError, IndexError):
        return None


def owner_live(identity, proc: Path = Path("/proc")) -> bool:
    pid = identity["pid"]
    birth = identity["birth"]
    return type(pid) is int and pid > 0 and isinstance(birth, str) and birth == process_birth(pid, proc)


def write_once(path: Path, value: dict) -> None:
    """Use an exclusive name so a disconnected installation cannot be resubmitted."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def run_compose(command: list[str]) -> CommandResult:
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return "uncertain"
    return "failed" if result.returncode else "completed"


def read_worker_status(docker_state: dict, restart_count: int) -> Health:
    if (docker_state.get("OOMKilled") or restart_count
            or docker_state.get("Status") in {"dead", "exited", "restarting"}):
        return "confirmed_failure"
    status = docker_state.get("Health", {}).get("Status")
    if not docker_state.get("Running"):
        return "unavailable"
    if status == "unhealthy":
        return "confirmed_failure"
    if status == "healthy":
        return "healthy"
    return "starting" if status == "starting" else "unavailable"


def switch_once(
    directory: Path,
    *,
    operation_id: UUID,
    package_sha: str,
    original_id: str,
    forward: list[str],
    restore: list[str],
    observe: Callable[[], Worker],
    quiet: Callable[[], bool],
    invoke: Callable[[list[str]], CommandResult] = run_compose,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    proc: Path = Path("/proc"),
) -> str:
    base = {"operation_id": str(operation_id), "package_sha256": package_sha}
    intent = directory / "switch-intent.json"
    if intent.exists():
        raise FileExistsError("Observe the original worker switch")
    initial = observe()
    pid = os.getpid()
    birth = process_birth(pid, proc)
    if initial != Worker("original", "healthy", original_id) or not quiet() or birth is None:
        raise ValueError("Original healthy worker and idle bot runtime required")
    write_once(intent, base | {"worker": asdict(initial), "owner": {"pid": pid, "birth": birth}})

    def wait_for(state: WorkerState, *, allow_original: bool = False) -> Worker:
        deadline = clock() + 90
        worker = observe()
        while clock() < deadline:
            if worker.state == state and worker.health in {"healthy", "confirmed_failure"}:
                break
            if worker.state == "foreign":
                break
            if allow_original and worker == initial:
                break
            sleep(0.5)
            worker = observe()
        return worker

    command = invoke(forward)
    if command == "uncertain":
        write_once(directory / "switch-result.json", base | {"result": "observe_original_operation"})
        return "observe_original_operation"
    worker = wait_for("candidate", allow_original=command == "failed")
    outcome = "observe_original_operation"
    if worker.state == "candidate" and worker.health == "healthy" and quiet() and observe() == worker:
        outcome = "worker_installed"
    elif command == "failed" and worker == initial:
        outcome = "original_worker_unchanged"
    elif (worker.state == "candidate" and worker.health == "confirmed_failure"
          and quiet() and observe() == worker):
        write_once(directory / "restore-intent.json", base | {"worker": asdict(worker)})
        if invoke(restore) != "uncertain":
            worker = wait_for("restored")
            if (worker.state == "restored" and worker.health == "healthy"
                    and quiet() and observe() == worker):
                outcome = "worker_restored"
    write_once(directory / "switch-result.json", base | {"result": outcome, "worker": asdict(worker)})
    return outcome


def observe_original(
    directory: Path,
    operation_id: UUID,
    package_sha: str,
    observe: Callable[[], Worker],
    proc: Path = Path("/proc"),
) -> dict:
    """Collect a new readback for the same operation, even after a lost SSH response."""
    path = directory / "switch-intent.json"
    current = observe()
    if not path.is_file():
        return {"status": "intent_missing", "worker": asdict(current)}
    intent = json.loads(path.read_bytes())
    wanted = {"operation_id": str(operation_id), "package_sha256": package_sha}
    if any(intent.get(k) != v for k, v in wanted.items()):
        raise ValueError("Original intent identity changed")
    result_path = directory / "switch-result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_bytes())
        if any(result.get(k) != v for k, v in wanted.items()):
            raise ValueError("Original result identity changed")
        result_value = result["result"]
    else:
        result_value = None
    return {
        "status": "original_live" if result_value is None and owner_live(intent["owner"], proc)
        else "readback",
        "recorded_result": result_value,
        "restore_attempted": (directory / "restore-intent.json").exists(),
        "worker": asdict(current),
    }
