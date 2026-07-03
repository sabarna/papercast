"""Console entry point for the PaperCast web UI.

Starts the FastAPI app with uvicorn. Equivalent to:

    uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    p = argparse.ArgumentParser(prog="papercast-web", description="Run the PaperCast web UI.")
    p.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="bind port (default: 8000)")
    p.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    args = p.parse_args(argv)

    print(f"PaperCast UI → http://{args.host}:{args.port}")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
