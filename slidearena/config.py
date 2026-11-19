"""Local storage. Everything lives in ~/.slidearena (override with SLIDEARENA_HOME).

API keys are stored only on this machine. A key can also be written as "env:VAR_NAME"
so that the secret stays in an environment variable instead of the file.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

_lock = threading.Lock()


def home() -> Path:
    p = Path(os.environ.get("SLIDEARENA_HOME") or (Path.home() / ".slidearena"))
    p.mkdir(parents=True, exist_ok=True)
    (p / "output").mkdir(exist_ok=True)
    return p


def _path(name: str) -> Path:
    return home() / name


def load(name: str, default):
    p = _path(name)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(name: str, data) -> None:
    with _lock:
        p = _path(name)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)


# ---------- models ----------

def list_models() -> list[dict]:
    return load("models.json", [])


def get_model(model_id: str) -> dict | None:
    return next((m for m in list_models() if m["id"] == model_id), None)


def upsert_model(entry: dict) -> dict:
    models = list_models()
    entry = dict(entry)
    if not entry.get("id"):
        entry["id"] = uuid.uuid4().hex[:8]
    old = next((m for m in models if m["id"] == entry["id"]), None)
    if old is not None:
        # an empty key in an update means "keep the existing key"
        if not entry.get("api_key"):
            entry["api_key"] = old.get("api_key", "")
        models = [entry if m["id"] == entry["id"] else m for m in models]
    else:
        models.append(entry)
    save("models.json", models)
    return entry


def find_model(base_url: str, model: str, protocol: str) -> dict | None:
    """An existing entry for the same endpoint and model name, so re-entering it updates the key
    instead of creating a duplicate."""
    base = (base_url or "").rstrip("/")
    return next((m for m in list_models() if m.get("protocol") == protocol and m.get("model") == model
                 and (m.get("base_url") or "").rstrip("/") == base), None)


def delete_model(model_id: str) -> bool:
    models = list_models()
    kept = [m for m in models if m["id"] != model_id]
    save("models.json", kept)
    return len(kept) != len(models)


def resolve_key(raw: str | None) -> str:
    raw = raw or ""
    if raw.startswith("env:"):
        return os.environ.get(raw[4:], "")
    return raw


def mask_key(raw: str | None) -> str:
    raw = raw or ""
    if not raw:
        return ""
    if raw.startswith("env:"):
        return raw
    return raw[:3] + "…" + raw[-4:] if len(raw) > 10 else "••••"


def public_model(m: dict) -> dict:
    out = {k: v for k, v in m.items() if k != "api_key"}
    out["api_key_masked"] = mask_key(m.get("api_key"))
    return out
