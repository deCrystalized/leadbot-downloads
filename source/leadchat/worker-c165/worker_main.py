"""Bind the single worker switch to C165 and the already published C164 nginx."""

from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from pathlib import Path
from uuid import UUID

from check_worker_cutover import (
    CONFIG,
    TARGET,
    bindings,
    compose_arguments,
    identify,
    pending_effects,
    sha,
    verify_compose,
    verify_original_config,
    worker_change,
)
from collect_prerequisites import DATABASE
from worker_switch import (
    Worker,
    observe_original,
    read_worker_status,
    switch_once,
    write_once,
)

STAGE = Path("/srv/leadchat/maintenance/leadbot-dialog-handoff-20261118-v1")
NGINX = STAGE.with_name("leadbot-settings-c180-20261118-v1")
WORKER_MANIFEST = "4f19786e4963494f1113e8537b377838ab911413f033bd1a7c92595921dbb0bd"
WORKER_COMPOSE = "9cf4a1cce612d499d6b7900715ea07a832e851f2ee14ef0f8218a70ace4e1a09"
NGINX_MANIFEST = "652686c7bcce73d5b91744a876420d1c8050bb3c6551b05e29535461168b7f3a"
PROJECT_LABEL = "com.docker.compose.project"
CONFIG_FILES_LABEL = "com.docker.compose.project.config_files"
WORKDIR_LABEL = "com.docker.compose.project.working_dir"
HASH_FILE = (
    "import hashlib,sys;from pathlib import Path;"
    "print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())"
)


def pinned(path, digest):
    if path.is_symlink():
        raise ValueError("Release file became a symlink")
    raw = path.read_bytes()
    if sha(raw) != digest:
        raise ValueError("Release input changed: " + path.name)
    return raw


def docker(args, body=None):
    result = subprocess.run(["docker", *args], input=body, capture_output=True, check=False,
                            text=True, timeout=25)
    if result.returncode:
        raise OSError("Docker command returned an error")
    return result.stdout


def inspect(id):
    rows = json.loads(docker(["inspect", id]))
    if len(rows) != 1 or rows[0]["Id"] != id:
        raise ValueError("Cannot prove original container identity")
    return rows[0]


def current_id(project, role):
    ids = docker(["ps", "-aq", "--no-trunc", "--filter", "label="+PROJECT_LABEL+"="+project,
                  "--filter", "label=com.docker.compose.service="+role]).splitlines()
    return ids[0] if len(ids) == 1 else None


def physical_worker(info):
    return {
        "Id": info["Id"],
        "Image": info["Image"],
        "Mounts": [{key: mount[key] for key in ("Source", "Destination", "Type", "RW")}
                   for mount in info["Mounts"]],
        "Config": {"Image": info["Config"]["Image"],
                   "Labels": {key: info["Config"]["Labels"][key]
                              for key in (PROJECT_LABEL, CONFIG_FILES_LABEL, WORKDIR_LABEL)}},
    }


class MainWorker:
    def __init__(self):
        if STAGE.is_symlink() or NGINX.is_symlink():
            raise ValueError("Release directories must be original directories")
        self.manifest = json.loads(pinned(STAGE / "manifest.json", WORKER_MANIFEST))
        self.package_sha = self.manifest["payload_sha256"]
        self.pins = json.loads(pinned(STAGE / "compose-read-only.json", WORKER_COMPOSE))
        if Path(self.manifest["remote_stage_proposed"]) != STAGE:
            raise ValueError("Release stage changed")
        pinned(STAGE / "payload.zip", self.package_sha)
        with zipfile.ZipFile(STAGE / "payload.zip") as bundle:
            for name, digest in self.manifest["entries_sha256"].items():
                if pinned(STAGE / name, digest) != bundle.read(name):
                    raise ValueError("Staged release does not match archive")
        ui = json.loads(pinned(NGINX / "package/manifest.json", NGINX_MANIFEST))
        deploy = json.loads((NGINX / "deployed.json").read_bytes())
        if (deploy["release"] != ui["release"] or deploy["step"] != "deployed"
                or set(deploy["roles"]) != {"nginx"}
                or deploy["verified_web_files"] != len(ui["web"])
                or deploy["public_health"] != {"status": 200, "version": ui["api_version"]}):
            raise ValueError("C164 nginx publication is not confirmed")
        self.protected = {role: row for role, row in ui["baseline_services"].items()
                          if role != "worker"}
        self.protected["nginx"] = deploy["roles"]["nginx"]
        self.original_id = self.manifest["worker_before_id"]
        self.input_pins = self.pins["compose_inputs_sha256"]
        self.original_path = STAGE / "original-worker.json"

    def original(self):
        return json.loads(self.original_path.read_bytes())

    def quiet(self):
        for role, expected in self.protected.items():
            verified = inspect(expected["id"])
            project = verified["Config"]["Labels"][PROJECT_LABEL]
            if (current_id(project, role) != expected["id"]
                    or verified["Image"] != expected["image"]
                    or verified["RestartCount"] != expected["restarts"]
                    or read_worker_status(verified["State"], verified["RestartCount"]) != "healthy"):
                raise ValueError("Protected service drifted: " + role)
        api = self.protected["api"]["id"]
        meta = json.loads(docker(["exec", "-i", api, "python", "-B", "-", CONFIG], DATABASE))
        verify_original_config(meta["configuration"])
        original = self.original()
        runtime_id = current_id(original["Config"]["Labels"][PROJECT_LABEL], "worker")
        if runtime_id is None:
            return False
        runtime = inspect(runtime_id)
        selected = bindings(runtime).get(CONFIG)
        if selected != bindings(original).get(CONFIG) or selected is None or selected[1:] != (
            "bind", False
        ):
            return False
        if runtime["State"]["Running"]:
            digest = docker(["exec", runtime_id, "python", "-B", "-c", HASH_FILE, CONFIG]).strip()
        else:
            digest = sha(Path(selected[0]).read_bytes())
        return digest == meta["manifest_sha"] and not pending_effects(meta["counts"])

    def prepare(self):
        original = physical_worker(inspect(self.original_id))
        if original["Image"] != self.manifest["worker_image_id"]:
            raise ValueError("Original worker image changed")
        if original["Image"] != docker(
            ["image", "inspect", original["Config"]["Image"], "--format", "{{.Id}}"]
        ).strip():
            raise ValueError("Configured worker tag changed")
        if docker(["exec", self.original_id, "python", "-B", "-c", HASH_FILE, TARGET]).strip() != (
            self.manifest["installed_driver_sha256"]
        ):
            raise ValueError("Original driver changed")
        args = compose_arguments(original, self.input_pins)
        old = json.loads(docker(args[1:] + ["config", "--format", "json"]))
        override = STAGE / "override.worker.json"
        new = json.loads(docker(args[1:] + ["-f", str(override), "config", "--format", "json"]))
        change = json.loads(override.read_bytes())["services"]["worker"]["volumes"][0]
        verify_compose(old, new, change, original["Config"]["Image"])
        write_once(self.original_path, original)

    def observe(self):
        try:
            original = self.original()
            id = current_id(original["Config"]["Labels"][PROJECT_LABEL], "worker")
            if id is None:
                return Worker("unavailable", "unavailable", None)
            live = inspect(id)
            status = read_worker_status(live["State"], live["RestartCount"])
            if live["State"]["Running"]:
                digest = docker(["exec", id, "python", "-B", "-c", HASH_FILE, TARGET]).strip()
            elif bindings(live).get(TARGET) == (str(STAGE / "assistant_driver.py"), "bind", False):
                digest = sha(pinned(STAGE / "assistant_driver.py",
                                    self.manifest["entries_sha256"]["assistant_driver.py"]))
            else:
                return Worker("unavailable", status, id)
            state = identify(original, live, self.manifest, list(self.input_pins), digest)
            return Worker(state, status, id)
        except (OSError, subprocess.TimeoutExpired):
            return Worker("unavailable", "unavailable", None)

    def apply(self, operation):
        original = self.original()
        args = compose_arguments(original, self.input_pins)
        if docker(["image", "inspect", original["Config"]["Image"], "--format", "{{.Id}}"]
                  ).strip() != original["Image"]:
            raise ValueError("Configured worker tag changed")
        return switch_once(
            STAGE, operation_id=operation, package_sha=self.package_sha,
            original_id=self.original_id, forward=worker_change(args, STAGE / "override.worker.json"),
            restore=worker_change(args), observe=self.observe, quiet=self.quiet,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "apply", "observe"))
    parser.add_argument("--operation", type=UUID, required=True)
    args = parser.parse_args()
    release = MainWorker()
    if args.mode == "prepare":
        release.prepare()
        result = {"status": "original_verified"}
    elif args.mode == "observe":
        result = observe_original(STAGE, args.operation, release.package_sha, release.observe)
    else:
        result = {"status": release.apply(args.operation)}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
