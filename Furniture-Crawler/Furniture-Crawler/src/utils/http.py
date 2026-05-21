"""HTTP request utilities"""

import json
import subprocess
from typing import Any, Dict, Optional


def fetch(url: str, timeout: int = 90) -> str:
    """Fetch URL content using curl"""
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-L",
            "--compressed",
            "--retry",
            "5",
            "--retry-delay",
            "1",
            "--retry-all-errors",
            "--max-time",
            str(timeout),
            url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if result.returncode != 0:
        raise RuntimeError(f"fetch failed: {url}\n{result.stderr.strip()}")
    return result.stdout


def request_url(
    url: str,
    timeout: int = 90,
    headers: Optional[Dict[str, str]] = None,
    json_payload: Optional[Dict[str, Any]] = None,
) -> str:
    """Make HTTP request with optional headers and JSON payload"""
    args = [
        "curl",
        "-sS",
        "-L",
        "--compressed",
        "--retry",
        "5",
        "--retry-delay",
            "1",
        "--retry-all-errors",
        "--max-time",
        str(timeout),
    ]
    for key, value in (headers or {}).items():
        args.extend(["-H", f"{key}: {value}"])
    if json_payload is not None:
        args.extend(
            [
                "-H",
                "Content-Type: application/json",
                "--data",
                json.dumps(json_payload, ensure_ascii=False),
            ]
        )
    args.append(url)
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if result.returncode != 0:
        raise RuntimeError(f"request failed: {url}\n{result.stderr.strip()}")
    return result.stdout


def fetch_json_url(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 90) -> Any:
    """Fetch JSON from URL"""
    return json.loads(request_url(url, timeout=timeout, headers=headers))


def post_json_url(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 90,
) -> Any:
    """Post JSON to URL"""
    return json.loads(request_url(url, timeout=timeout, headers=headers, json_payload=payload))