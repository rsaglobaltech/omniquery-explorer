"""In-memory token-bucket rate limiter for the Web adapter.

The limiter is keyed by either the ``X-API-Key`` header (preferred) or
the remote client IP. It is intentionally simple — no Redis, no
distributed state — because the typical deployment is a single
container. Operators who fan out across replicas should put a real
gateway (Cloudflare, nginx, Envoy) in front and disable this layer.

Algorithm: token bucket with refill rate = ``rate_per_minute / 60`` per
second and capacity equal to the same number. Burst behaviour matches
the configured rate so users cannot stack quota across idle minutes.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from omniquery.config import WebSettings


@dataclass
class _Bucket:
    """Per-identity bucket state."""

    tokens: float
    last_refill: float


class TokenBucketRateLimiter:
    """Async-safe token bucket. One instance is shared by all requests."""

    def __init__(self, settings: WebSettings) -> None:
        self._settings = settings
        # Pre-compute refill numbers so the hot path stays tight.
        self._capacity = float(settings.rate_limit_per_minute)
        self._refill_per_sec = self._capacity / 60.0
        self._buckets: dict[str, _Bucket] = {}
        # asyncio.Lock guards the dict against concurrent reads/writes
        # under starlette's threaded request handling.
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._settings.rate_limit_per_minute > 0

    async def check(self, identity: str) -> None:
        """Consume one token for ``identity``; raise 429 when empty.

        ``identity`` is whatever the caller chose as the bucket key
        (API key, IP, ...). The bucket is created on demand.
        """
        if not self.enabled:
            return
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets.get(identity)
            if bucket is None:
                # Fresh identity → start full so first request always
                # passes; subsequent ones are gated by the refill rate.
                bucket = _Bucket(tokens=self._capacity, last_refill=now)
                self._buckets[identity] = bucket
            # Refill: linear with elapsed time, capped at capacity.
            elapsed = now - bucket.last_refill
            bucket.tokens = min(
                self._capacity,
                bucket.tokens + elapsed * self._refill_per_sec,
            )
            bucket.last_refill = now

            if bucket.tokens < 1.0:
                # Tell the client how long until the next token arrives
                # (RFC 6585 / 7231) so retry logic can back off cleanly.
                retry_after = max(1, int((1.0 - bucket.tokens) / self._refill_per_sec))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.tokens -= 1.0


def identity_for(request: Request) -> str:
    """Pick the bucket key for a request.

    Authenticated callers (X-API-Key) get a per-key bucket so a buggy
    integration cannot starve other tenants. Anonymous callers fall back
    to the client IP — when behind a proxy this is the proxy IP, which
    is acceptable for the local-single-container default deployment.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{api_key}"
    # ``request.client`` may be None for ASGI scopes without a peer
    # (e.g. tests that send raw bytes).
    host = request.client.host if request.client else "anon"
    return f"ip:{host}"
