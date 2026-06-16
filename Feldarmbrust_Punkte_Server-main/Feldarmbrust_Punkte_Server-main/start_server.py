#!/usr/bin/env python3
"""Start script for the Feldarmbrust scoring server."""

import os
import sys
import threading
import time
import webbrowser

import uvicorn


def app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def open_browser_later(url: str) -> None:
    def _open() -> None:
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    base_dir = app_base_dir()
    os.chdir(base_dir)

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not getattr(sys, "frozen", False) and not os.path.exists("app"):
        print("Error: app/ folder not found.")
        print("Start the EXE from the server folder.")
        sys.exit(1)

    if not os.environ.get("FELDARMBRUST_API_KEY"):
        password = input("Choose server password / API key (Enter = 1234): ").strip() or "1234"
        os.environ["FELDARMBRUST_API_KEY"] = password
    else:
        password = os.environ["FELDARMBRUST_API_KEY"]

    certfile = os.environ.get("FELDARMBRUST_TLS_CERTFILE") or os.path.join(base_dir, "certs", "server.crt")
    keyfile = os.environ.get("FELDARMBRUST_TLS_KEYFILE") or os.path.join(base_dir, "certs", "server.key")
    if not os.path.exists(certfile) or not os.path.exists(keyfile):
        certfile = None
        keyfile = None

    scheme = "https" if certfile and keyfile else "http"
    url = f"{scheme}://localhost:8000"

    print("Feldarmbrust scoring server")
    print("=" * 50)
    print("Server is starting...")
    print(f"URL: {url}")
    print(f"API docs: {url}/docs")
    print(f"Web page: {url}")
    print(f"Password/API key: {password}")
    print("TLS: enabled" if scheme == "https" else "TLS: disabled")
    print("=" * 50)
    print("Press CTRL+C to stop")
    print()

    open_browser_later(url)

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )


if __name__ == "__main__":
    main()
