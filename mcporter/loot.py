"""
Loot table translation (block drops).

Minecraft block loot is data-driven; the common case is a single
`minecraft:item` entry that drops the block itself or a derived item.  We
extract that to set the Luanti node `drop`.
"""

from __future__ import annotations

from typing import Optional

from . import util
from .jarfs import VirtualFS
from .recipes import IdMapper


def build_loot_map(fs: VirtualFS, namespace: str, mapper: IdMapper,
                   resource_root: str = "") -> dict[str, str]:
    """Return {block_name: luanti_drop_id} for the mod's block loot tables."""
    out: dict[str, str] = {}
    markers = (
        f"data/{namespace}/loot_table",
        f"data/{namespace}/loot_tables",
    )
    for p in fs.all_paths():
        if not p.endswith(".json"):
            continue
        if not any(m in p for m in markers):
            continue
        if "/blocks/" not in p and "/block/" not in p:
            continue
        name = p.rsplit("/", 1)[-1][:-5]
        data = fs.read(p)
        if not data:
            continue
        try:
            table = util.load_json(data)
        except Exception:
            continue
        drop = _first_item_drop(table)
        if drop:
            mapped, _ = mapper.map_ident(drop, allow_group=False)
            if mapped:
                out[name] = mapped
    return out


def _first_item_drop(table: dict) -> Optional[str]:
    for pool in table.get("pools", []):
        for entry in pool.get("entries", []):
            ent = _walk_entry(entry)
            if ent:
                return ent
    return None


def _walk_entry(entry: dict) -> Optional[str]:
    etype = str(entry.get("type", "")).split(":")[-1]
    if etype == "item":
        return entry.get("name")
    if etype in ("alternatives", "group", "sequence"):
        for child in entry.get("children", []):
            r = _walk_entry(child)
            if r:
                return r
    return None
