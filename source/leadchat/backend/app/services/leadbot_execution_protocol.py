"""Private references and exact checked office proposals; no credential or executor tunnel."""

import hashlib
import hmac
import json
import math
import re
import secrets
import uuid

PATH = "/api/leadchat/native-research"
DOMAIN = b"leadbot-native-research-v1\x00"
MAX_REQUEST = 16000
MAX_OFFICE_REQUEST = 120000
MAX_PROPOSAL = 100000
MAX_RESPONSE = 1000000
AUTH_HEADERS = ("x-lb-exec-time", "x-lb-exec-nonce", "x-lb-exec-signature")
OFFICE_HEADER = "x-lb-exec-office"


class ExecutionError(ValueError):
    pass


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw, limit):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
        raise ExecutionError("Bounded native command required")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ExecutionError("Duplicate native command field")
            value[key] = item
        return value

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ExecutionError("Nonfinite value")),
        )
    except (ValueError, UnicodeError, RecursionError):
        raise ExecutionError("Strict native JSON required") from None


def identifier(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def request_limit(value):
    return (
        MAX_OFFICE_REQUEST
        if value.get("operation") in ("reserve_office", "consume_office")
        else MAX_REQUEST
    )


def _office(args, op):
    required = {
        "cid",
        "source_sha256",
        "kind",
        "operation_id",
        "revision",
        "proposal",
        "snapshot_hash",
    }
    if op == "consume_office":
        required.add("grant_id")
    if (
        set(args) != required
        or args.get("kind") != "create_crm"
        or not identifier(args.get("cid"))
        or any(
            not isinstance(args.get(k), str) or not re.fullmatch(r"[a-f0-9]{64}", args[k])
            for k in ("source_sha256", "snapshot_hash")
        )
        or any(
            not isinstance(args.get(k), str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,200}", args[k])
            for k in required - {"cid", "source_sha256", "snapshot_hash", "kind", "proposal"}
        )
    ):
        raise ExecutionError("Exact native office source and action required")
    proposal = args["proposal"]
    fields = {
        "revision",
        "form_reference",
        "dir",
        "lead",
        "prep",
        "territory",
        "sel",
        "readiness",
        "flags",
        "allowLive",
        "followup",
    }
    if (
        not isinstance(proposal, dict)
        or set(proposal) != fields
        or proposal.get("revision") != args["revision"]
        or not isinstance(proposal.get("form_reference"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", proposal["form_reference"])
        or proposal.get("dir") not in ("mnc", "bt", "kp")
        or proposal.get("allowLive") is not False
        or proposal.get("readiness") != "ready"
        or proposal.get("flags") != []
        or any(
            not isinstance(proposal.get(k), dict)
            for k in ("lead", "prep", "territory", "sel", "followup")
        )
    ):
        raise ExecutionError("Exact checked office proposal required")
    raw = encode(proposal)
    if len(raw) > MAX_PROPOSAL or sha(raw) != args["snapshot_hash"]:
        raise ExecutionError("Original office snapshot is changed or oversized")
    forbidden = {
        "authorization",
        "headers",
        "cookie",
        "apikey",
        "accesstoken",
        "password",
        "secret",
        "identityproof",
        "jwt",
        "nonce",
        "proof",
        "signature",
        "authheaders",
    }

    def private(value, depth=0):
        if depth > 20:
            raise ExecutionError("Office proposal nesting exceeds budget")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or re.sub(r"[_ -]", "", key.casefold()) in forbidden:
                    raise ExecutionError(
                        "Credential-bearing office proposal rejected before journal"
                    )
                private(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                private(item, depth + 1)

    private(proposal)


def check(value):
    fields = {
        "v",
        "command_id",
        "operation",
        "principal_id",
        "operator_id",
        "run_id",
        "generation",
        "arguments",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or type(value["v"]) is not int
        or (value["v"] != 1)
        or (
            not all(
                identifier(value[k])
                for k in ("command_id", "principal_id", "operator_id", "run_id")
            )
        )
        or (type(value["generation"]) is not int)
        or (not 1 <= value["generation"] <= 2**63 - 1)
        or (not isinstance(value["arguments"], dict))
    ):
        raise ExecutionError("Exact native actor and launch required")
    args, op = (value["arguments"], value["operation"])
    if op == "recover":
        if set(args) != {"command_id"} or not identifier(args["command_id"]):
            raise ExecutionError("Exact original command required")
    elif op == "notify_office":
        required = {
            "cid",
            "source_sha256",
            "work_id",
            "notification_id",
            "create_command_id",
            "crm_request_id",
            "snapshot_hash",
            "form_reference",
            "card_sha256",
            "dispatch_before",
        }
        if (
            set(args) != required
            or not all(
                identifier(args.get(k)) for k in ("cid", "notification_id", "create_command_id")
            )
            or any(
                not isinstance(args.get(k), str) or not re.fullmatch(r"[a-f0-9]{64}", args[k])
                for k in (
                    "source_sha256",
                    "work_id",
                    "snapshot_hash",
                    "form_reference",
                    "card_sha256",
                )
            )
            or not isinstance(args.get("crm_request_id"), str)
            or not re.fullmatch(r"[1-9][0-9]{0,11}", args["crm_request_id"])
            or type(args.get("dispatch_before")) not in (int, float)
            or not math.isfinite(args["dispatch_before"])
        ):
            raise ExecutionError("Exact original office notification reference required")
    elif op in ("reserve_office", "consume_office"):
        _office(args, op)
    elif op in ("reserve_action", "consume_action"):
        required = {"cid", "source_sha256", "kind", "operation_id", "revision"}
        if args.get("kind") == "reply":
            required.add("draft_id")
        if op == "consume_action":
            required.add("grant_id")
        if (
            set(args) != required
            or args.get("kind") not in ("claim", "reply")
            or (not identifier(args.get("cid")))
            or (not isinstance(args.get("source_sha256"), str))
            or (not re.fullmatch("[a-f0-9]{64}", args["source_sha256"]))
            or any(
                not isinstance(args.get(k), str)
                or not re.fullmatch("[A-Za-z0-9:_-]{1,200}", args[k])
                for k in required - {"cid", "source_sha256", "kind"}
            )
        ):
            raise ExecutionError("Exact source-bound native action references required")
    elif op in ("inspect", "prepare", "status", "finalize", "cancel"):
        required = (
            {"cid", "source_sha256"}
            if op == "inspect"
            else {"cid", "source_sha256", "purpose"}
            if op == "prepare"
            else {"cid", "source_sha256", "request_id", "revision", "research_job_id"}
        )
        if (
            set(args) != required
            or not identifier(args.get("cid"))
            or (not isinstance(args.get("source_sha256"), str))
            or (not re.fullmatch("[a-f0-9]{64}", args["source_sha256"]))
        ):
            raise ExecutionError("Exact source identity required")
        if op == "prepare":
            if args["purpose"] not in ("reply", "intake_form_v1", "visual_observation_v1"):
                raise ExecutionError("Unsupported native preparation purpose")
        elif op != "inspect" and (
            any(
                not isinstance(args[k], str) or not re.fullmatch("[A-Za-z0-9:_-]{1,200}", args[k])
                for k in ("request_id", "revision")
            )
            or not isinstance(args["research_job_id"], str)
            or (not re.fullmatch("[a-f0-9]{32}|", args["research_job_id"]))
        ):
            raise ExecutionError("Exact original request and job required")
    else:
        raise ExecutionError("Unadmitted native operation")
    if len(encode(value)) > request_limit(value):
        raise ExecutionError("Native command exceeds its operation budget")
    return value


def _key(key):
    if (
        not isinstance(key, bytes)
        or not 32 <= len(key) <= 512
        or any(chr(c).isspace() for c in key)
    ):
        raise ExecutionError("Native execution authentication unavailable")
    return key


def _message(raw, stamp, nonce):
    return (
        DOMAIN
        + b"POST\n"
        + PATH.encode()
        + b"\n"
        + stamp.encode()
        + b"\n"
        + nonce.encode()
        + b"\n"
        + sha(raw).encode()
    )


def request(key, value, *, now):
    raw = encode(check(value))
    if len(raw) > request_limit(value):
        raise ExecutionError("Native command exceeds budget")
    stamp, nonce = (str(int(now)), secrets.token_urlsafe(24))
    signature = hmac.new(_key(key), _message(raw, stamp, nonce), hashlib.sha256).hexdigest()
    headers = {"X-LB-Exec-Time": stamp, "X-LB-Exec-Nonce": nonce, "X-LB-Exec-Signature": signature}
    if request_limit(value) == MAX_OFFICE_REQUEST:
        headers["X-LB-Exec-Office"] = "1"
    return raw, headers


def verify(key, raw, headers, *, now):
    stamp, nonce, signature = (headers.get(k, "") for k in AUTH_HEADERS)
    if (
        not isinstance(stamp, str)
        or not re.fullmatch("\\d{10}", stamp)
        or abs(now - int(stamp)) > 30
        or (not isinstance(nonce, str))
        or (not re.fullmatch("[A-Za-z0-9_-]{32}", nonce))
        or (not isinstance(signature, str))
        or (not re.fullmatch("[a-f0-9]{64}", signature))
        or (not isinstance(raw, bytes))
        or (not 0 < len(raw) <= MAX_OFFICE_REQUEST)
    ):
        raise ExecutionError("Native command authentication expired or invalid")
    expected = hmac.new(_key(key), _message(raw, stamp, nonce), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ExecutionError("Native command authentication failed")
    value = check(decode(raw, MAX_OFFICE_REQUEST))
    announcement = "1" if request_limit(value) == MAX_OFFICE_REQUEST else None
    if headers.get(OFFICE_HEADER) != announcement:
        raise ExecutionError("Office framing and signed operation disagree")
    return value, nonce


def response_signature(key, raw, nonce, status):
    if type(status) is not int or not 200 <= status <= 599:
        raise ExecutionError("Exact native HTTP result required")
    message = (
        DOMAIN
        + b"response\n"
        + nonce.encode()
        + b"\n"
        + str(status).encode()
        + b"\n"
        + sha(raw).encode()
    )
    return hmac.new(_key(key), message, hashlib.sha256).hexdigest()


def verify_response(key, raw, nonce, status, signature):
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, response_signature(key, raw, nonce, status)
    ):
        raise ExecutionError("Native command response binding failed")
    return decode(raw, MAX_RESPONSE)
