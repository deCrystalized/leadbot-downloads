"""Run the paired fixture with an explicit Internet-socket deny guard."""

import json
import os
import socket
import sys

attempts = 0


def offline(event, args):
    global attempts
    if event in ("socket.connect", "socket.bind", "socket.sendto") and getattr(
        args[0], "family", None
    ) in (socket.AF_INET, socket.AF_INET6):
        attempts += 1
        raise AssertionError("Internet sockets are forbidden in this test")
    if event == "socket.getaddrinfo":
        attempts += 1
        raise AssertionError("DNS is forbidden in this test")
    if event == "open" and isinstance(args[0], (str, bytes)) and os.fsdecode(args[0]).endswith(
        (".key", "secrets.env")
    ):
        raise AssertionError("Credential reads are forbidden in this test")


sys.addaudithook(offline)
import pytest  # noqa: E402 - the audit guard must cover test framework imports too

code = pytest.main(sys.argv[1:])
print(json.dumps({"status": int(code), "internet_socket_attempts": attempts}))
raise SystemExit(code or int(attempts > 0))
