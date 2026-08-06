"""
run.py - production entrypoint for the compiled Photobooth Robot build.

Dev still uses `uvicorn main:app --reload`. This module exists because a
Nuitka build needs a real callable entrypoint rather than the uvicorn CLI,
and because production must never enable --reload (the reloader re-executes
the interpreter, which does not exist in a compiled bundle).

Nothing secret lives here - it stays readable on purpose. All the actual
logic sits in the compiled modules it imports.
"""
from __future__ import annotations

import uvicorn

import config
from main import app


def main() -> None:
    # Pass the app object, not the "main:app" import string: string form
    # makes uvicorn re-import by name, which is needless indirection in a
    # frozen bundle.
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level="info",
        # ws protocol is the pure-python `websockets` impl (see requirements.txt)
        ws="websockets",
    )


if __name__ == "__main__":
    main()
