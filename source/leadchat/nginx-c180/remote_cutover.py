"""Switch only the frozen role-specific calendar candidates, with guarded reverse-order rollback."""

import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

from remote_preflight import container, run, verify_nginx_inputs

ROOT = Path(__file__).resolve().parent


def main():
    owner = ROOT / "cutover-owner.json"
    with owner.open("x") as stream:
        stream.write(json.dumps({"pid": os.getpid(), "started_at": time.time(),
            "proc_start_ticks": Path(f"/proc/{os.getpid()}/stat").read_text().split()[21]}) + "\n")
    assert not (ROOT / "deployed.json").exists(), "Already deployed; inspect current state instead"
    ready = json.loads((ROOT / "preflight-ready.json").read_text())
    manifest = json.loads((ROOT / "package/manifest.json").read_text())
    verify_nginx_inputs(container("nginx"), manifest, ROOT / "nginx-compose-order.json")
    assert manifest["frontend_only"] and set(ready["roles"]) == {"nginx"} and not manifest["roles"]
    assert (
        hashlib.sha256((ROOT / "release-package.tar.gz").read_bytes()).hexdigest()
        == (ROOT / "release-archive-sha256.txt").read_text().strip()
    )
    for role, row in ready["roles"].items():
        assert container(role)["Id"] == row["before_id"], (role, "Concurrent deployment")
        assert (
            run(["docker", "image", "inspect", row["tag"], "--format", "{{.Id}}"]).strip()
            == row["image"]
        )
    for role, row in ready["protected_services"].items():
        current = container(role)
        assert current["Id"] == row["id"] and current["RestartCount"] == row["restarts"], role
    inventory = """import hashlib,json
from pathlib import Path
r=Path('/srv/app/app')
files={str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest()
       for p in r.rglob('*') if p.is_file() and '__pycache__' not in p.parts
       and (p.suffix=='.py' or str(p.relative_to(r))=='bots/scenarios/primary_intake.json')}
print(json.dumps(files))
"""
    for checked_role in ["api", "worker", "scheduler"]:
        expected = manifest["baseline_app"][checked_role]
        assert json.loads(run([
            "docker", "exec", container(checked_role)["Id"], "python", "-c", inventory
        ])) == expected, (checked_role, "Parallel runtime changed after freeze")

    def verify_private_binds():
        for role, expected in manifest["baseline_private_binds"].items():
            actual = [{"source": m["Source"], "destination": m["Destination"], "rw": m["RW"], "type": m["Type"]}
                      for m in container(role)["Mounts"] if m["Destination"].startswith("/srv/app/app/")]
            assert {m["destination"]:m for m in actual} == {m["destination"]:m for m in expected}, role
            assert len(actual) == len(expected)
    verify_private_binds()
    record = {
        "release": ready["release"],
        "roles": {},
        "schema_changed": False,
        "customer_writes_by_agent": False,
        "protected_services": ready["protected_services"],
    }

    def checkpoint(step):
        record["step"] = step
        record["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (ROOT / "cutover-state.json").write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps({"step": step, "utc": record["updated_at"]}), flush=True)

    def switch(role, rollback=False):
        row = ready["roles"][role]
        override = row["rollback"] if rollback else row["candidate"]
        expected = row["base_image"] if rollback else row["image"]
        run(
            row["prefix"]
            + [
                "-f",
                override,
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--pull",
                "never",
                "--timeout",
                "5" if role == "nginx" else "120" if role in {"worker", "scheduler"} else "20",
                role,
            ],
            timeout=180 if role in {"worker", "scheduler"} else 80,
        )
        deadline = time.monotonic() + 90
        while True:
            current = container(role)
            assert (
                current["Image"] == expected
                and current["State"]["Running"]
                and not current["State"]["OOMKilled"]
            ), role
            assert current["RestartCount"] == 0, role
            if current["State"].get("Health", {}).get("Status") == "healthy":
                return {"id": current["Id"], "image": expected, "healthy": True, "restarts": 0}
            assert time.monotonic() < deadline, (role, "Health timeout")
            time.sleep(0.5)

    switched = []
    checkpoint("verified-before-switch")
    try:
        for role in [r for r in ["worker", "scheduler", "api", "nginx"] if r in ready["roles"]]:
            assert container(role)["Id"] == ready["roles"][role]["before_id"], role
            switched.append(role)
            checkpoint("switching-" + role)
            record["roles"][role] = switch(role)
            checkpoint("healthy-" + role)
        for changed_role in [r for r in ["api", "worker", "scheduler"] if r in manifest["roles"]]:
            assert (
                json.loads(
                    run(
                        ["docker", "exec", container(changed_role)["Id"], "python", "-c", inventory]
                    )
                )
                == manifest["roles"][changed_role]["expected_app"]
            )
        hashes = run(
            [
                "docker",
                "exec",
                container("nginx")["Id"],
                "sha256sum",
                *["/" + n for n in manifest["web"]],
            ]
        )
        actual = {
            line.split("  ", 1)[1].removeprefix("/"): line.split("  ", 1)[0]
            for line in hashes.splitlines()
        }
        assert actual == manifest["web"], "Published web bytes mismatch"
        assert run(["docker", "exec", container("nginx")["Id"], "sha256sum", "/srv/leadchat-design/classic.html"]).split()[0] == manifest["classic_html_sha256"]
        for role, row in ready["protected_services"].items():
            current = container(role)
            assert current["Id"] == row["id"] and current["RestartCount"] == row["restarts"], role
            assert current["State"].get("Health", {}).get("Status") == "healthy", role
        with urllib.request.urlopen(
            "https://188-225-34-82.sslip.io/api/health", timeout=15
        ) as response:
            health = json.load(response)
            assert response.status == 200 and health["version"] == manifest["api_version"], health
        verify_private_binds()
        record["public_health"] = {"status": 200, "version": health["version"]}
        record["verified_web_files"] = len(actual)
        checkpoint("deployed")
        (ROOT / "deployed.json").write_text(json.dumps(record, indent=2) + "\n")
    except Exception:
        for role in reversed(switched):
            current = container(role)
            if current["Image"] not in {
                ready["roles"][role]["image"],
                ready["roles"][role]["base_image"],
            }:
                record.setdefault("external_drift", []).append(role)
                continue
            record.setdefault("rollback", {})[role] = switch(role, True)
        checkpoint("rolled-back")
        (ROOT / "rolled-back.json").write_text(json.dumps(record, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
