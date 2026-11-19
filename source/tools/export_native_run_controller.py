"""Export the exact, tested Run controller to LeadChat's frontend (no transport)."""

import argparse
import hashlib
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("frontend", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "ext/assistant-native.js"
    result = subprocess.run(
        ["node", "-e", "process.stdout.write(require(process.argv[1]).createRun.toString())", str(source)],
        check=True, capture_output=True, text=True,
    ).stdout
    assert result.startswith("function createRun(deps){")
    checksum = hashlib.sha256(result.encode()).hexdigest()
    content = (
        "/* Generated from LeadBot ext/assistant-native.js; do not edit independently.\n"
        f" * createRun SHA256: {checksum}\n */\n"
        '/* eslint @typescript-eslint/no-unused-vars: ["error", { "caughtErrorsIgnorePattern": "^_error$" }] */\n'
        f"export const createRun = {result};\n"
    )
    target = args.frontend.resolve(strict=True) / "src/features/bot-dialogs/nativeRunController.js"
    if args.check:
        assert target.read_text() == content, "Run controllers differ; stop packaging"
    else:
        target.write_text(content)
    print(f"Exact createRun verified: {checksum}")


if __name__ == "__main__":
    main()
