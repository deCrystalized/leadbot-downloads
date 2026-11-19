"""Build and check reversible reporting candidates; never switch running services here."""

import copy
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NGINX_ORDER_SHA256 = "4e7e31543bc01683d78c6118dc0bfca83ba6ed66d7a3ca2366ded50e1a338a2a"


def run(args, *, timeout=90):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(
            "Preflight command failed: " + str(args[:3]) + " " + result.stderr[-1800:]
        )
    return result.stdout


def container(role):
    ids = run(
        ["docker", "ps", "-q", "--filter", "label=com.docker.compose.service=" + role]
    ).split()
    assert len(ids) == 1, (role, len(ids))
    return json.loads(run(["docker", "inspect", ids[0]]))[0]


def prefix(info):
    labels = info["Config"]["Labels"]
    args = [
        "docker",
        "compose",
        "--project-name",
        labels["com.docker.compose.project"],
        "--project-directory",
        labels["com.docker.compose.project.working_dir"],
    ]
    for file in labels["com.docker.compose.project.config_files"].split(","):
        assert Path(file).is_file(), file
        args += ["-f", file]
    return args


def verify_nginx_inputs(info, manifest, receipt):
    raw = receipt.read_bytes()
    if hashlib.sha256(raw).hexdigest() != NGINX_ORDER_SHA256:
        raise ValueError("Nginx Compose order receipt changed")
    frozen = json.loads(raw)
    inputs = info["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")
    pins = manifest["nginx_compose_sha256"]
    if (
        info["Id"] != frozen["id"]
        or inputs != frozen["compose_order"]
        or set(inputs) != set(pins)
        or frozen["sha256_by_file"] != pins
    ):
        raise ValueError("Nginx Compose inputs drifted")
    actual = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in inputs}
    if actual != pins:
        raise ValueError("Nginx Compose input bytes changed")


def main():
    assert not (ROOT / "preflight-ready.json").exists(), "Do not overwrite an accepted preflight"
    assert shutil.disk_usage(ROOT).free > 1024 * 1024 * 1024, "Insufficient disk headroom"
    expected_sha = (ROOT / "release-archive-sha256.txt").read_text().strip()
    assert (
        hashlib.sha256((ROOT / "release-package.tar.gz").read_bytes()).hexdigest() == expected_sha
    )
    with tarfile.open(ROOT / "release-package.tar.gz") as archive:
        assert all(
            not m.name.startswith("/") and ".." not in Path(m.name).parts
            for m in archive.getmembers()
        )
        archive.extractall(ROOT, filter="data")
    manifest = json.loads((ROOT / "package/manifest.json").read_text())
    verify_nginx_inputs(container("nginx"), manifest, ROOT / "nginx-compose-order.json")
    assert manifest["frontend_only"] and set(manifest["bases"]) == {"nginx"} and not manifest["roles"]
    before = {
        role: container(role)
        for role in ["api", "worker", "scheduler", "nginx", "postgres", "redis"]
    }
    for role, expected in manifest["baseline_services"].items():
        info = before[role]
        assert info["Id"] == expected["id"] and info["Image"] == expected["image"]
        assert info["RestartCount"] == expected["restarts"]
        assert info["State"].get("Health", {}).get("Status") == "healthy"
    for role, expected in manifest["baseline_private_binds"].items():
        mounts = [{"source": m["Source"], "destination": m["Destination"], "rw": m["RW"], "type": m["Type"]}
                  for m in before[role]["Mounts"] if m["Destination"].startswith("/srv/app/app/")]
        actual_by_destination = {mount["destination"]: mount for mount in mounts}
        expected_by_destination = {mount["destination"]: mount for mount in expected}
        assert len(mounts) == len(actual_by_destination) == len(expected) == len(expected_by_destination)
        assert actual_by_destination == expected_by_destination, (role, "Private bindings changed")
    for role, image in manifest["bases"].items():
        assert before[role]["Image"] == image, (role, "Concurrent deployment; stop")
        assert before[role]["State"].get("Health", {}).get("Status") == "healthy", role
        assert before[role]["RestartCount"] == 0 and not before[role]["State"]["OOMKilled"], role
        if role != "nginx":
            for name in manifest["roles"][role]["changed"]:
                path = Path("/srv/app/app") / name
                assert not any(
                    path.is_relative_to(mount["Destination"]) for mount in before[role]["Mounts"]
                ), (role, "Code bind mount")
    roles = {}
    inventory = """import ast,hashlib,json
from pathlib import Path
root=Path('/srv/app/app')
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
       for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts
       and (p.suffix=='.py' or
            str(p.relative_to(root))=='bots/scenarios/primary_intake.json')}
print('APP_INVENTORY='+json.dumps(files))
"""
    for role in ["api", "worker", "scheduler"]:
        output = run(["docker", "exec", before[role]["Id"], "python", "-c", inventory])
        actual = json.loads(
            next(
                line.split("=", 1)[1]
                for line in output.splitlines()
                if line.startswith("APP_INVENTORY=")
            )
        )
        expected = manifest["baseline_app"][role]
        extra = [name for name in expected if name not in actual]
        if extra:
            script = "import hashlib,json;from pathlib import Path;r=Path('/srv/app/app');names=" + repr(extra) + ";print(json.dumps({n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in names}))"
            actual.update(json.loads(run(["docker", "exec", before[role]["Id"], "python", "-c", script])))
        assert actual == expected, (role, "Runtime source drift")
    for role in manifest["bases"]:
        info = before[role]
        image_base = manifest["bases"][role]
        base_tag = "local/leadchat-stats-base:" + role + "-" + image_base[7:19]
        tag = "local/leadchat-" + role + ":" + manifest["release"]
        run(["docker", "tag", image_base, base_tag])
        assert (
            run(["docker", "image", "inspect", base_tag, "--format", "{{.Id}}"]).strip()
            == image_base
        )
        result = run(
            [
                "docker",
                "build",
                "--pull=false",
                "--network=none",
                "-t",
                tag,
                str(ROOT / "package" / role),
            ],
            timeout=180,
        )
        (ROOT / ("build-" + role + ".log")).write_text(result)
        image = run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"]).strip()
        if role == "nginx":
            def static_files(source):
                text = run(["docker", "run", "--rm", "--network=none", "--read-only", "--entrypoint", "find", source,
                            "/usr/share/nginx/html", "-type", "f", "-exec", "sha256sum", "{}", "+"], timeout=60)
                return {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in text.splitlines()}

            old_static, new_static = static_files(image_base), static_files(image)
            assert all(new_static.get(name) == digest for name, digest in old_static.items()), "An old asset changed or disappeared"
            added = sorted(set(new_static) - set(old_static))
            assert added and all(name.startswith(tuple("/usr/share/nginx/html/assets/" + manifest["release"] + "/" + d + "/" for d in ["new", "classic"])) for name in added)
            classic = run(["docker", "run", "--rm", "--network=none", "--read-only", "--entrypoint", "sha256sum", image,
                           "/srv/leadchat-design/classic.html"]).split()[0]
            assert classic == manifest["classic_html_sha256"]
            new_shell = run(["docker", "run", "--rm", "--network=none", "--read-only", "--entrypoint", "sha256sum", image, "/srv/leadchat-design/new.html"]).split()[0]
            assert new_shell == manifest["new_html_sha256"]
            (ROOT / "static-retention.json").write_text(json.dumps({"baseline_files": len(old_static), "candidate_files": len(new_static),
                "all_baseline_files_preserved": True, "added_files": len(added), "classic_html_updated_and_verified": True}) + "\n")
        command = prefix(info)
        old = json.loads(run(command + ["config", "--format", "json"]))
        override = {"image": tag}
        restore = {"image": image_base}
        if role == "nginx":
            override["stop_grace_period"] = "5s"
            restore["stop_grace_period"] = old["services"][role].get("stop_grace_period", "10s")
        if role != "nginx":
            override["environment"] = {"APP_VERSION": manifest["release"]}
            restore["environment"] = {
                "APP_VERSION": old["services"][role].get("environment", {}).get("APP_VERSION", "")
            }
        candidate = ROOT / ("candidate-" + role + ".json")
        rollback = ROOT / ("rollback-" + role + ".json")
        candidate.write_text(json.dumps({"services": {role: override}}) + "\n")
        rollback.write_text(json.dumps({"services": {role: restore}}) + "\n")
        new = json.loads(run(command + ["-f", str(candidate), "config", "--format", "json"]))
        old_compare, new_compare = copy.deepcopy(old), copy.deepcopy(new)
        old_compare["services"][role].pop("image")
        assert new_compare["services"][role].pop("image") == tag
        if role == "nginx":
            old_compare["services"][role].pop("stop_grace_period", None)
            assert new_compare["services"][role].pop("stop_grace_period") == "5s"
        if role != "nginx":
            old_compare["services"][role].setdefault("environment", {}).pop("APP_VERSION", None)
            assert (
                new_compare["services"][role]["environment"].pop("APP_VERSION")
                == manifest["release"]
            )
        assert old_compare == new_compare, (role, "Unrelated effective configuration change")
        if role == "nginx":
            probe = run(
                command
                + ["-f", str(candidate), "run", "--rm", "--no-deps", "-T", role, "nginx", "-t"]
            )
        else:
            changed = manifest["roles"][role]["changed"]
            probe_code = inventory + "\nimport importlib\n"
            probe_code += (
                "from app.core.workspace_time import BUSINESS_TZ\n"
                "assert BUSINESS_TZ.key=='Asia/Vladivostok'\n"
                "from app.services.audit import msk_day_range\n"
                "from datetime import date,datetime,UTC\n"
                "assert msk_day_range(date(2026,1,1),date(2026,1,1))[0]"
                "==datetime(2025,12,31,14,tzinfo=UTC)\n"
                "from app.services.address_funnel import week_bounds\n"
                "assert week_bounds(date(2026,11,9))[0]==datetime(2026,11,8,21,tzinfo=UTC)\n"
            )
            for name in changed:
                if name.endswith(".py"):
                    probe_code += (
                        "importlib.import_module("
                        + repr("app." + name[:-3].replace("/", "."))
                        + ")\n"
                    )
            if role == "api":
                probe_code += (
                    "from app.schemas.bots import BotCreate,BotWrite\n"
                    "assert BotCreate(name='fictional').schedule.timezone=='Asia/Vladivostok'\n"
                    "assert BotWrite(name='fictional').schedule.timezone=='Europe/Moscow'\n"
                )
            else:
                probe_code += "from app.integrations.avito.errors import AvitoTokenResponseError\n"
            env = {
                "ENV": "development",
                "DATABASE_URL": "sqlite+aiosqlite://",
                "REDIS_URL": "redis://127.0.0.1:1/0",
                "JWT_SECRET": "fictional-no-network-preflight-0123456789abcdef",
                "TOKEN_ENC_KEY": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=",
                "AVITO_CLIENT_ID": "fictional",
                "AVITO_CLIENT_SECRET": "fictional",
                "MEDIA_SIGN_KEY": "fictional",
                "AI_FAKE": "1",
                "APP_VERSION": manifest["release"],
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            args = ["docker", "run", "--rm", "--network=none", "--entrypoint", "python"]
            protected = "/srv/app/app/services/assistant_runtime.py"
            mounts = [mount for mount in info["Mounts"] if mount["Destination"] == protected]
            if role in {"api", "worker"}:
                assert len(mounts) == 1 and mounts[0]["Type"] == "bind" and not mounts[0]["RW"]
                assert Path(mounts[0]["Source"]).is_file()
                args += [
                    "--mount",
                    "type=bind,src=" + mounts[0]["Source"] + ",dst=" + protected + ",readonly",
                ]
            else:
                assert not mounts
            for key, value in env.items():
                args += ["-e", key + "=" + value]
            probe = run(args + [tag, "-B", "-c", probe_code], timeout=90)
            actual = json.loads(
                next(
                    line.split("=", 1)[1]
                    for line in probe.splitlines()
                    if line.startswith("APP_INVENTORY=")
                )
            )
            assert actual == manifest["roles"][role]["expected_app"], (
                role,
                "Candidate source/bind mismatch",
            )
        (ROOT / ("preflight-" + role + ".txt")).write_text(probe)
        roles[role] = {
            "image": image,
            "tag": tag,
            "prefix": command,
            "candidate": str(candidate),
            "rollback": str(rollback),
            "before_id": info["Id"],
            "base_image": image_base,
        }
        print(json.dumps({"role": role, "built": image, "preflight": True}), flush=True)
    for role, info in before.items():
        after = container(role)
        assert after["Id"] == info["Id"] and after["RestartCount"] == info["RestartCount"], role
    result = {
        "release": manifest["release"],
        "roles": roles,
        "protected_services": {
            role: {"id": before[role]["Id"], "restarts": before[role]["RestartCount"]}
            for role in before
            if role not in roles
        },
        "running_services_changed": False,
    }
    (ROOT / "preflight-ready.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"ready": True, "running_services_changed": False}))


if __name__ == "__main__":
    main()
