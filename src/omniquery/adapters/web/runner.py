"""Console-script entrypoint that boots the FastAPI app under uvicorn."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "omniquery.adapters.web.app:app",
        # Default to 0.0.0.0 so the container is reachable from the
        # host network without extra plumbing. Override WEB_HOST when
        # deploying behind a single-interface proxy.
        host=os.getenv("WEB_HOST", "0.0.0.0"),  # nosec B104
        port=int(os.getenv("WEB_PORT", "8000")),
        reload=os.getenv("WEB_RELOAD", "false").lower() in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    main()
