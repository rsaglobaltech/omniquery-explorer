"""Lightweight API key auth dependency.

Reads accepted keys from ``WEB_API_KEYS`` (comma-separated). If unset and
``environment != production``, auth is bypassed. In production, an unset
or empty key list raises at startup.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from omniquery.config import get_settings


def _accepted_keys() -> set[str]:
    raw = os.getenv("WEB_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    settings = get_settings()
    keys = _accepted_keys()
    if settings.environment != "production" and not keys:
        return
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WEB_API_KEYS must be configured in production.",
        )
    if x_api_key is None or x_api_key not in keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


ApiKeyDep = Depends(require_api_key)
