"""One-attempt private research transport over the existing WireGuard bridge.

This client never grants calls, starts Auto, claims a dialog or sends a reply.
The caller must durably store its exact command before calling submit. A lost
reply requires a new read-only recover command for that original command ID.
"""

import asyncio
import time
from collections.abc import Callable

import httpx

from app.services import assistant_identity
from app.services import leadbot_execution_protocol as wire


class NativeTransportUncertain(ValueError):
    """No retry/fallback: the original private command may have completed."""


class NativeResearchClient:
    def __init__(
        self,
        *,
        enabled: bool = False,
        key: Callable[[], bytes | None] = assistant_identity.proof_key,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ):
        if type(enabled) is not bool or not callable(key) or not callable(clock):
            raise ValueError("Trusted native transport settings required")
        self.enabled, self.key, self.transport, self.clock = enabled, key, transport, clock

    async def submit(self, command: dict[str, object]) -> tuple[dict[str, object], int]:
        if not self.enabled:
            raise ValueError("Native execution transport is disabled")
        # Signing material is process-private; no browser JWT/header/proxy is
        # accepted. The only HTTP endpoint is inside the existing VPN bridge.
        secret = self.key()
        if not isinstance(secret, bytes):
            raise ValueError("Private native execution key is unavailable")
        raw, headers = wire.request(secret, command, now=self.clock())
        if secret in raw:
            raise ValueError("Credential reflected in command; no request")
        try:
            async with asyncio.timeout(30):
                async with httpx.AsyncClient(
                    base_url="http://10.10.0.2:8788",
                    trust_env=False,
                    follow_redirects=False,
                    transport=self.transport,
                    timeout=httpx.Timeout(25, connect=5, write=5, pool=5),
                ) as client:
                    async with client.stream(
                        "POST",
                        wire.PATH,
                        content=raw,
                        headers={
                            **headers,
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                    ) as response:
                        if (
                            response.headers.get("content-type", "").split(";")[0]
                            != "application/json"
                        ):
                            raise ValueError("Private response type mismatch")
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > wire.MAX_RESPONSE:
                                raise ValueError("Private response exceeds budget")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                        if secret in body:
                            raise ValueError("Credential reflected in response; do not persist")
                        result = wire.verify_response(
                            secret,
                            body,
                            headers["X-LB-Exec-Nonce"],
                            response.status_code,
                            response.headers.get("X-LB-Exec-Signature"),
                        )
                        if (
                            not isinstance(result, dict)
                            or type(result.get("ok")) is not bool
                            or result.get("can_send_or_create") is not False
                        ):
                            raise ValueError("Private response cannot grant customer actions")
                        return result, response.status_code
        except Exception:
            # Do not stringify HTTP errors: they may contain headers, a URL
            # or reflected provider data. No second network request is made.
            raise NativeTransportUncertain(
                "Read the original command; no automatic repeat"
            ) from None
