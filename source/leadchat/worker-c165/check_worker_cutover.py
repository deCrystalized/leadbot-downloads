"""Verify an original worker or the exact C165 replacement without changing either."""

from __future__ import annotations

import hashlib
from pathlib import Path

TARGET = "/srv/app/app/services/assistant_driver.py"
CONFIG = "/etc/leadbot-native-crm-only.json"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bindings(info):
    mounts = {
        mount["Destination"]: (mount["Source"], mount["Type"], mount["RW"])
        for mount in info["Mounts"]
    }
    if len(mounts) != len(info["Mounts"]):
        raise ValueError("Duplicate mount destination")
    return mounts


def files(info):
    return info["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")


def healthy(info):
    return (
        info["State"]["Running"]
        and not info["State"]["OOMKilled"]
        and info["RestartCount"] == 0
        and info["State"].get("Health", {}).get("Status") == "healthy"
    )


def identify(original, current, manifest, before_inputs, actual_driver_sha):
    """Return original, candidate, restored or foreign using exact Compose provenance."""
    if current["Image"] != manifest["worker_image_id"]:
        return "foreign"
    original_mounts = bindings(original)
    if TARGET in original_mounts or CONFIG not in original_mounts:
        raise ValueError("Unexpected original mounts")
    candidate = Path(manifest["remote_stage_proposed"])
    candidate_mounts = original_mounts | {TARGET: (str(candidate / "assistant_driver.py"),
                                                    "bind", False)}
    actual_mounts = bindings(current)
    actual_files = files(current)
    if (actual_files == before_inputs and actual_mounts == original_mounts
            and actual_driver_sha == manifest["installed_driver_sha256"]):
        return "original" if current["Id"] == original["Id"] else "restored"
    if (current["Id"] != original["Id"]
            and actual_files == [*before_inputs, str(candidate / "override.worker.json")]
            and actual_mounts == candidate_mounts
            and actual_driver_sha == manifest["entries_sha256"]["assistant_driver.py"]):
        return "candidate"
    return "foreign"


def compose_arguments(original, before_pins):
    labels = original["Config"]["Labels"]
    paths = files(original)
    if paths != list(before_pins):
        raise ValueError("Compose input order changed")
    if any(sha(Path(name).read_bytes()) != before_pins[name] for name in paths):
        raise ValueError("Compose file changed")
    arguments = [
        "docker", "compose", "--project-name", labels["com.docker.compose.project"],
        "--project-directory", labels["com.docker.compose.project.working_dir"],
    ]
    for name in paths:
        arguments.extend(("-f", name))
    return arguments


def verify_compose(base, candidate, expected_bind, expected_image):
    """The candidate keeps the configured image and changes exactly one read-only mount."""
    old = base["services"]["worker"]
    new = candidate["services"]["worker"]
    if old["image"] != expected_image or new["image"] != expected_image:
        raise ValueError("Configured worker image changed")
    additions = [volume for volume in new["volumes"] if volume["target"] == TARGET]
    if (len(additions) != 1
            or any(additions[0].get(k) != expected_bind[k] for k in
                   ("target", "source", "type", "read_only"))
            or additions[0].get("bind", {}).get("create_host_path", False) is not False
            or any(volume["target"] == TARGET for volume in old["volumes"])):
        raise ValueError("Unexpected driver bind")
    other_volumes = [volume for volume in new["volumes"] if volume["target"] != TARGET]
    comparable = candidate | {
        "services": candidate["services"] | {"worker": new | {"volumes": other_volumes}},
    }
    if comparable != base:
        raise ValueError("Unrelated effective Compose changes")


def verify_original_config(config):
    if not (
        config["auto_ready"] is True and config["crm_only"] is True
        and config["notifications_enabled"] is False and config["office_enabled"] is True
        and config["max_dialogs"] == 1 and config["scan_batch"] == 1
    ):
        raise ValueError("C160 runtime flags drifted")


def worker_change(arguments, override=None):
    stages = [*arguments]
    if override is not None:
        stages.extend(("-f", str(override)))
    return [*stages, "up", "-d", "--no-deps", "--no-build", "--pull", "never",
            "--timeout", "120", "worker"]


def pending_effects(counts):
    terminal = {
        "assistant_native_actions": {"claimed", "screened", "blocked", "stopped", "expired",
                                     "delivered", "delivery_stopped"},
        "assistant_research_work": {"ready", "parked", "blocked", "stopped", "expired"},
        "assistant_native_office": {"completed", "stopped", "expired", "blocked"},
        "assistant_native_outbound": {"delivered", "delivery_stopped"},
        "assistant_native_notifications": {"sent", "stopped", "expired", "blocked"},
    }
    return bool(counts["assistant_runs"].get("running")) or any(
        set(counts[table]) - stages for table, stages in terminal.items()
    )


def rollback_decision(state, probe):
    """An incomplete readback or foreign state cannot authorize mutations."""
    if state in {"original", "restored"}:
        return "no_changes"
    if state == "candidate" and probe == "confirmed_failure":
        return "restore_worker"
    return "observe_original_operation"
