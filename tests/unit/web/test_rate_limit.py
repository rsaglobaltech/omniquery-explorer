from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from omniquery.adapters.web.rate_limit import (
    TokenBucketRateLimiter,
    identity_for,
)
from omniquery.config import WebSettings


@pytest.mark.asyncio
async def test_first_n_requests_pass():
    """A fresh bucket starts full, so 'capacity' requests must succeed."""
    limiter = TokenBucketRateLimiter(WebSettings(rate_limit_per_minute=5))
    for _ in range(5):
        await limiter.check("alice")


@pytest.mark.asyncio
async def test_overflow_raises_429_with_retry_after():
    limiter = TokenBucketRateLimiter(WebSettings(rate_limit_per_minute=2))
    await limiter.check("bob")
    await limiter.check("bob")
    with pytest.raises(HTTPException) as ei:
        await limiter.check("bob")
    assert ei.value.status_code == 429
    assert "Retry-After" in (ei.value.headers or {})


@pytest.mark.asyncio
async def test_buckets_isolated_per_identity():
    limiter = TokenBucketRateLimiter(WebSettings(rate_limit_per_minute=1))
    await limiter.check("alice")
    # bob still has its full bucket and must pass.
    await limiter.check("bob")
    with pytest.raises(HTTPException):
        await limiter.check("alice")


@pytest.mark.asyncio
async def test_disabled_when_rate_zero():
    limiter = TokenBucketRateLimiter(WebSettings(rate_limit_per_minute=0))
    assert limiter.enabled is False
    # Any number of requests must pass through without consuming tokens.
    for _ in range(50):
        await limiter.check("anyone")


@pytest.mark.asyncio
async def test_refill_replenishes_tokens(monkeypatch: pytest.MonkeyPatch):
    """Forwarding monotonic time should add tokens at the configured rate."""
    limiter = TokenBucketRateLimiter(WebSettings(rate_limit_per_minute=60))
    # Drain the bucket completely.
    for _ in range(60):
        await limiter.check("carol")
    with pytest.raises(HTTPException):
        await limiter.check("carol")
    # Fast-forward 1 second → refill_per_sec = 1.0 → one token available.
    import omniquery.adapters.web.rate_limit as mod

    fake_time = mod.time.monotonic() + 1.0
    monkeypatch.setattr(mod.time, "monotonic", lambda: fake_time)
    await limiter.check("carol")  # passes after refill
    # No second token yet — next call should fail again.
    with pytest.raises(HTTPException):
        await limiter.check("carol")


def test_identity_prefers_api_key():
    req = MagicMock()
    req.headers = {"X-API-Key": "abc"}
    req.client = MagicMock(host="10.0.0.1")
    assert identity_for(req) == "key:abc"


def test_identity_falls_back_to_ip():
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock(host="10.0.0.1")
    assert identity_for(req) == "ip:10.0.0.1"


def test_identity_handles_missing_client():
    req = MagicMock()
    req.headers = {}
    req.client = None
    assert identity_for(req) == "ip:anon"
