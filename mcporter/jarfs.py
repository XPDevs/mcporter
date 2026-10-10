"""
Virtual filesystem over a Minecraft mod.

A mod may be:
  * a compiled .jar / .zip  (ZIP archive)
  * an extracted directory
  * a source tree (has src/main/resources and/or src/main/java)

We expose a uniform, read-only interface keyed by normalised POSIX paths.
"""

from __future__ import annotations

import io
import os
import zipfile
from typing import Iterable, Optional


def _norm(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


class VirtualFS:
    """Read-only virtual filesystem."""

    def __init__(self, root: str):
        self.root = root
        self._zip: Optional[zipfile.ZipFile] = None
        self._zip_names: list[str] = []
        self._dir_listing: dict[str, list[str]] | None = None
        self._dir_files: dict[str, bytes] | None = None
        if os.path.isdir(root):
            self.kind = "dir"
            self._index_dir()
        elif zipfile.is_zipfile(root):
            self.kind = "zip"
            self._zip = zipfile.ZipFile(root, "r")
            self._zip_names = [_norm(n) for n in self._zip.namelist() if not n.endswith("/")]
        else:
            raise ValueError(f"not a directory or zip: {root}")

    # -- indexing -----------------------------------------------------------
    def _index_dir(self) -> None:
        self._dir_files = {}
        self._dir_listing = {}
        for base, _dirs, files in os.walk(self.root):
            rel = _norm(os.path.relpath(base, self.root))
            if rel == ".":
                rel = ""
            self._dir_listing.setdefault(rel, [])
            for f in files:
                full = os.path.join(base, f)
                key = _norm(os.path.join(rel, f)) if rel else f
                self._dir_files[key] = full  # store path, read lazily
                parent = os.path.dirname(key)
                self._dir_listing.setdefault(parent, []).append(f)

    # -- queries ------------------------------------------------------------
    def all_paths(self) -> list[str]:
        if self.kind == "zip":
            return list(self._zip_names)
        return list(self._dir_files.keys())

    def exists(self, path: str) -> bool:
        path = _norm(path)
        if self.kind == "zip":
            return path in set(self._zip_names)
        return path in self._dir_files

    def read(self, path: str) -> Optional[bytes]:
        path = _norm(path)
        if self.kind == "zip":
            try:
                return self._zip.read(path)
            except KeyError:
                return None
        full = self._dir_files.get(path) if self._dir_files else None
        if full is None:
            return None
        with open(full, "rb") as fh:
            return fh.read()

    def text(self, path: str) -> Optional[str]:
        data = self.read(path)
        if data is None:
            return None
        return data.decode("utf-8-sig", errors="replace")

    def find(self, predicate) -> list[str]:
        return [p for p in self.all_paths() if predicate(p)]

    def glob(self, prefix: str, suffix: str = "") -> list[str]:
        prefix = _norm(prefix)
        out = []
        for p in self.all_paths():
            if p.startswith(prefix) and p.endswith(suffix):
                out.append(p)
        return out

    # -- pull out nested archives ------------------------------------------
    def nested_jars(self, prefix: str = "META-INF/jarjar") -> list[tuple[str, zipfile.ZipFile]]:
        """Forge/NeoForge ship bundled dependency jars inside the mod jar."""
        out = []
        if self.kind != "zip":
            return out
        for p in self.all_paths():
            if p.startswith(prefix) and p.endswith(".jar"):
                data = self.read(p)
                if data:
                    try:
                        out.append((p, zipfile.ZipFile(io.BytesIO(data))))
                    except zipfile.BadZipFile:
                        continue
        return out

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None
