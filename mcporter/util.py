"""Small stdlib-only helpers used across mcporter."""

from __future__ import annotations

import json
import os
import re
from typing import Any


_NS_RE = re.compile(r"^([a-z0-9_.-]+):(.+)$")


def split_id(ident: str) -> tuple[str, str]:
    """Split a namespaced Minecraft id into (namespace, path).

    'minecraft:iron_ingot' -> ('minecraft', 'iron_ingot')
    'create:zinc'          -> ('create', 'zinc')
    'iron_ingot'           -> ('minecraft', 'iron_ingot')
    '#c:ingots'            -> ('#c', 'ingots')   (tags keep their '#')
    """
    ident = ident.strip()
    m = _NS_RE.match(ident)
    if m:
        return m.group(1), m.group(2)
    return "minecraft", ident


def is_tag(ident: str) -> bool:
    return ident.startswith("#")


def tag_id(ident: str) -> str:
    return ident[1:] if ident.startswith("#") else ident


def lua_name(path: str) -> str:
    """Sanitize an id path for use as an identifier / filename stem."""
    out = re.sub(r"[^a-zA-Z0-9_]", "_", path)
    if out and out[0].isdigit():
        out = "_" + out
    return out


def lua_quote(s: str) -> str:
    """Quote a string for inclusion in generated Lua source."""
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '"' + s + '"'


def load_json(data: bytes | str) -> Any:
    """Parse JSON, tolerating a UTF-8 BOM and lenient formatting."""
    if isinstance(data, bytes):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data
    # Some mod metadata files contain trailing commas / comments. Strip them.
    text = _strip_jsonc(text)
    return json.loads(text)


_JSONC_LINE = re.compile(r"(?m)//[^\n]*$")
_JSONC_TRAIL = re.compile(r",(\s*[}\]])")


def _strip_jsonc(text: str) -> str:
    # Remove // comments that are not inside strings (heuristic, good enough
    # for mod metadata which is machine generated).
    out = []
    i = 0
    n = len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    cleaned = "".join(out)
    cleaned = _JSONC_TRAIL.sub(r"\1", cleaned)
    return cleaned


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TB"


def ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def titleize(path: str) -> str:
    """'zinc_ingot' -> 'Zinc Ingot'."""
    words = re.split(r"[_\s]+", path)
    return " ".join(w[:1].upper() + w[1:] for w in words if w)
