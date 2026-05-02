"""Export all knowledge base entries from a running backend to a JSON file.

The dump can then be checked into the repo (or shared) and replayed against
any other environment (local Docker, ECS, demo, …) via `import_knowledge.py`.

Usage:

    python backend/scripts/export_knowledge.py
    python backend/scripts/export_knowledge.py --base-url http://localhost:8001 \\
        --username admin --password change-me-in-production \\
        --output backend/seed_data/knowledge.json

Only uses the Python standard library so it can run inside the project's venv
without extra dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _request(url: str, method: str = "GET", payload: dict | None = None, token: str | None = None) -> dict | list:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} from {url}: {detail}") from e


def login(base_url: str, username: str, password: str) -> str:
    data = _request(
        f"{base_url}/api/auth/login",
        method="POST",
        payload={"username": username, "password": password},
    )
    if not isinstance(data, dict) or "access_token" not in data:
        raise SystemExit(f"Login response missing access_token: {data}")
    return data["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("KB_BASE_URL", "http://localhost:8001"))
    parser.add_argument("--username", default=os.environ.get("KB_USERNAME", "admin"))
    parser.add_argument(
        "--password",
        default=os.environ.get("KB_PASSWORD", "change-me-in-production"),
    )
    parser.add_argument(
        "--output",
        default="backend/seed_data/knowledge.json",
        help="Output JSON path (relative to current working dir).",
    )
    args = parser.parse_args()

    print(f"[export] logging in to {args.base_url} as {args.username}")
    token = login(args.base_url, args.username, args.password)
    print("[export] login ok")

    print("[export] fetching /api/knowledge …")
    data = _request(f"{args.base_url}/api/knowledge", token=token)
    if not isinstance(data, list):
        raise SystemExit(f"Unexpected response shape: {type(data).__name__}")

    entries = [
        {
            "title": e.get("title"),
            "content": e.get("content"),
            "source": e.get("source"),
            "category": e.get("category"),
        }
        for e in data
    ]

    out_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"[export] wrote {len(entries)} entries to {out_path}")


if __name__ == "__main__":
    main()
