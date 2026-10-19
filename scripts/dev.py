"""Start, inspect or stop the standalone core development stack."""

from pathlib import Path

from ai_idp.dev import main

if __name__ == "__main__":
    raise SystemExit(
        main(
            Path(__file__).resolve().parents[1],
            project="ai-idp-core-dev",
            url="http://127.0.0.1:8000/docs",
        )
    )
