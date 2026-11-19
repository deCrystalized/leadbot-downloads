"""Read-only preflight for the already frozen C164/C165 packages on Main."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import zipfile
from pathlib import Path

from check_worker_cutover import pending_effects, sha, verify_original_config

HERE = Path(__file__).resolve().parent
REVIEW = HERE.parent / "review"
TRANSPORT = HERE.parents[1] / "C160-practical-main-launch266-v1/review/transport.json"

DATABASE = """
import asyncio, hashlib, json, os, sys
from pathlib import Path
import asyncpg

async def main():
    raw = Path(sys.argv[1]).read_bytes()
    cfg = json.loads(raw)
    conn = await asyncpg.connect(
        os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"),
        server_settings={"default_transaction_read_only":"on","statement_timeout":"5000"},
    )
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            assert await conn.fetchval("SHOW transaction_read_only") == "on"
            pairs = (
                ("assistant_runs", "state"), ("assistant_native_actions", "stage"),
                ("assistant_research_work", "stage"), ("assistant_native_office", "stage"),
                ("assistant_native_outbound", "state"), ("assistant_native_notifications", "stage"),
            )
            counts = {}
            for table, column in pairs:
                rows = await conn.fetch(f"SELECT {column},count(*) FROM {table} GROUP BY {column}")
                counts[table] = dict(rows)
            print(json.dumps({
                "last_update":str(await conn.fetchval("SELECT max(updated_at) FROM assistant_runs")),
                "counts":counts,
                "manifest_sha":hashlib.sha256(raw).hexdigest(),
                "configuration":{key:cfg[key] for key in ("auto_ready","crm_only",
                    "notifications_enabled","office_enabled","max_dialogs","scan_batch")},
            }))
    finally:
        await conn.close()
asyncio.run(main())
"""

REMOTE = r"""
import hashlib, json, pathlib, subprocess, sys, urllib.request

def docker(args, body=None):
    proc = subprocess.run(
        ["docker", *args], input=body, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=25, check=False,
    )
    if proc.returncode:
        raise ValueError("Docker observation failed")
    return proc.stdout

payload = json.load(sys.stdin)
roles = payload["services"]
containers = json.loads(docker(["inspect", *[row["id"] for row in roles.values()]]))
for (role, row), item in zip(roles.items(), containers, strict=True):
    project = item["Config"]["Labels"]["com.docker.compose.project"]
    current = docker(["ps", "-aq", "--no-trunc", "--filter",
        "label=com.docker.compose.project="+project, "--filter",
        "label=com.docker.compose.service="+role]).decode().splitlines()
    assert current == [row["id"]], ("Container changed", role)
    assert item["Image"] == row["image"]
    assert item["RestartCount"] == row["restarts"]
    assert item["State"]["Health"]["Status"] == "healthy"
    assert item["State"]["Running"] and not item["State"]["OOMKilled"]
    if role in payload["compose"]:
        pins = payload["compose"][role]
        paths = item["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")
        assert paths == payload["compose_order"][role] and set(paths) == set(pins), (
            "Compose order changed", role)
        assert all(hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()==pins[path]
                   for path in paths), ("Compose bytes changed", role)
        tag = item["Config"]["Image"]
        configured = docker(["image","inspect",tag,"--format","{{.Id}}"]).decode().strip()
        assert configured == item["Image"], ("Configured image changed", role)
    if role == "worker":
        actual = docker(["exec", item["Id"], "python", "-B", "-c",
            "import sys,hashlib;from pathlib import Path;"
            "print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())",
            payload["driver_path"]]).decode().strip()
        assert actual == payload["driver_sha"]

for name in payload["new_paths"]:
    path = pathlib.Path(name)
    assert not path.exists() and not path.is_symlink(), ("Stage already exists", name)
meta = json.loads(docker(
    ["exec", "-i", roles["api"]["id"], "python", "-B", "-", payload["manifest_path"]],
    payload["database_code"].encode(),
))
worker_manifest = docker(
    ["exec", roles["worker"]["id"], "python", "-B", "-c",
     "import sys,hashlib;from pathlib import Path;"
     "print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())", payload["manifest_path"]],
).decode().strip()
assert worker_manifest == meta["manifest_sha"], "API and worker configuration differ"
with urllib.request.urlopen("https://188-225-34-82.sslip.io/api/health", timeout=8) as response:
    assert response.status == 200 and json.load(response)["version"] == payload["api_version"]
print(json.dumps({"healthy_pinned_roles":list(roles),"state":meta,
                  "shared_manifest":True,"public_health":200,
                  "driver_sha":actual,
                  "compose_hash_counts":{k:len(v) for k,v in payload["compose"].items()},
                  "compose_argument_counts":{k:len(v) for k,v in payload["compose_order"].items()},
                  "proposed_stages_absent":True}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        parser.error("Choose a new receipt")
    worker = json.loads((HERE / "manifest.json").read_bytes())
    pins = json.loads((HERE / "compose-read-only.json").read_bytes())
    ui = json.loads((REVIEW / "package/manifest.json").read_bytes())
    assert sha((HERE / "payload.zip").read_bytes()) == worker["payload_sha256"]
    with zipfile.ZipFile(HERE / "payload.zip") as bundle:
        assert sorted(bundle.namelist()) == sorted(worker["entries_sha256"])
        assert all(sha(bundle.read(name)) == digest
                   for name, digest in worker["entries_sha256"].items())
    assert sha((REVIEW / "release-package.tar.gz").read_bytes()) == (
        REVIEW / "release-archive-sha256.txt"
    ).read_text().strip()
    assert pins["worker_id"] == worker["worker_before_id"] == ui["baseline_services"]["worker"]["id"]
    order = (HERE.parent / "C166-release-control/nginx-compose-order.json").read_bytes()
    assert sha(order) == "7b0bf5cd4bd702cdf9cb7c7da8cc2fa14b3bb64487412cc1ab3f2ab5566010f5"
    nginx = json.loads(order)
    assert nginx["sha256_by_file"] == ui["nginx_compose_sha256"]
    payload = {
        "services": ui["baseline_services"],
        "compose": {"nginx": ui["nginx_compose_sha256"], "worker": pins["compose_inputs_sha256"]},
        "compose_order": {"nginx": nginx["compose_order"], "worker": list(pins["compose_inputs_sha256"])},
        "driver_path": worker["expected_mount"], "driver_sha": worker["installed_driver_sha256"],
        "new_paths": [
            "/srv/leadchat/maintenance/" + ui["release"], worker["remote_stage_proposed"],
        ],
        "manifest_path": "/etc/leadbot-native-crm-only.json",
        "api_version": ui["api_version"],
        "database_code": DATABASE,
    }
    config = json.loads(TRANSPORT.read_bytes())
    command = config["ssh"]["main"] + [shlex.join(["python3", "-B", "-c", REMOTE])]
    process = subprocess.run(command, input=json.dumps(payload), capture_output=True, text=True,
                             check=False, timeout=45)
    if process.returncode:
        last = process.stderr.splitlines()[-1:] or ["Observation unavailable"]
        raise RuntimeError(last[0][:220] if last[0].startswith("AssertionError:") else
                           "Read-only observation unavailable")
    result = json.loads(process.stdout)
    state = result["state"]
    verify_original_config(state["configuration"])
    result["pending_native_effects"] = pending_effects(state["counts"])
    with os.fdopen(os.open(args.receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(json.dumps({key: item for key, item in result.items() if key != "state"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
