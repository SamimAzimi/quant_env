"""Secrets come from environment variables — never from committed source.

A `.env` file at the project root is loaded on import (python-dotenv when
installed, a minimal parser otherwise). Copy `.env.example` to `.env` and
fill in your own keys; `.env` is gitignored.
"""
from __future__ import annotations

import os

from .paths import PROJECT_ROOT

_DOTENV = PROJECT_ROOT / ".env"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(_DOTENV)
        return
    except ImportError:
        pass
    if not _DOTENV.exists():
        return
    for line in _DOTENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()


def get_secret(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def require_secret(name: str) -> str:
    """Like get_secret but raises with a helpful message when unset."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required secret {name!r}. Set it in your environment "
            f"or in {_DOTENV} (see .env.example)."
        )
    return value
