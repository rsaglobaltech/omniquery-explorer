"""Console-script entrypoint that boots the Streamlit UI.

Streamlit launches its own server; we simply invoke ``streamlit run``
pointing at the ``app.py`` module so the same script works from the
installed wheel without extra arguments.

The optional ``[ui]`` extra carries the heavy `streamlit` dependency,
so the import is lazy — users that never call ``omniquery-ui`` are not
forced to install pandas + streamlit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    try:
        # Importing the CLI inside ``streamlit.web.cli`` forwards every
        # remaining argv flag (e.g. ``--server.port``) to the runtime.
        from streamlit.web import cli as stcli  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "omniquery-ui requires the 'ui' extra. "
            "Install with: pip install 'omniquery-explorer[ui]'"
        ) from exc

    app_path = Path(__file__).with_name("app.py")
    # The Streamlit CLI parses sys.argv directly, so we splice in
    # ``streamlit run <app>`` while preserving any extra user args.
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        os.getenv("UI_HOST", "0.0.0.0"),
        "--server.port",
        os.getenv("UI_PORT", "8501"),
        *sys.argv[1:],
    ]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
