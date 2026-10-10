"""
Recipe translation.

Converts Minecraft recipe JSON (all data-driven recipe types) into Luanti
`core.register_craft` definitions.  Ingredient resolution understands:

  * the mod's own namespace
  * vanilla ids (via the vanilla_map dictionary)
  * item tags -> Luanti crafting groups where a mapping exists,
    otherwise the first concrete member of the tag
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from . import util
from .assets import VanillaAssets
from .jarfs import VirtualFS
from .vanilla_map import map_vanilla, tag_to_group


@dataclass
class TranslatedRecipe:
    kind: str
    lua: dict
    source: str
    note: str = ""


class TagIndex:
    """Collects item tags from the mod and (optionally) vanilla."""

    def __init__(self, fs: VirtualFS, namespace: str, vanilla: Optional[VanillaAssets],
                 resource_root: str = ""):
        self.tags: dict[str, list[str]] = {}
        self.namespace = namespace
        self.vanilla = vanilla
        self.resource_root = resource_root or ""
        self.data_prefix = f"{self.resource_root}data/"
        self._scan_mod(fs)

    def _scan_mod(self, fs: VirtualFS) -> None:
        marker = f"data/{self.namespace}/"
        for p in fs.all_paths():
            if not p.endswith(".json") or "/tags/" not in p:
                continue
            if marker not in p:
                continue
            if "/tags/item" not in p and "/tags/items" not in p:
                if "/tags/block" in p or "/tags/blocks" in p:
                    continue
            parts = p.split("/")
            if "data" not in parts:
                continue
            di = parts.index("data")
            if di + 1 >= len(parts) or parts[di + 1] != self.namespace:
                continue
            try:
                data = util.load_json(fs.read(p) or b"{}")
            except Exception:
                continue
            values = data.get("values", [])
            key = self._tag_key_from_parts(parts, di)
            members = [self._norm(v) for v in values]
            self.tags.setdefault(key, []).extend(members)

    def _tag_key_from_parts(self, parts: list[str], di: int) -> str:
        ns = parts[di + 1]
        # parts[di+2] is registry (item/items/block/blocks), rest is subpath+file
        ti = parts.index("tags")
        name_parts = parts[ti + 2:]
        return f"{ns}:{'/'.join(name_parts)}"

    def _norm(self, value) -> str:
        if isinstance(value, dict):
            value = value.get("id", "")
        value = str(value)
        if value.startswith("#"):
            return value
        ns, path = util.split_id(value)
        return f"{ns}:{path}"

    def resolve(self, tag: str, seen: Optional[set] = None) -> list[str]:
        """Flatten a tag to a list of concrete item ids (no nested tags)."""
        seen = seen or set()
        if tag in seen:
            return []
        seen.add(tag)
        out: list[str] = []
        for member in self.tags.get(tag, []):
            if member.startswith("#"):
                out.extend(self.resolve(member[1:], seen))
            else:
                out.append(member)
        if not out and self.vanilla is not None:
            ns, path = util.split_id(tag)
            if ns == "minecraft":
                data = self.vanilla.tag("item", path)
                if data:
                    for v in data.get("values", []):
                        v = v.get("id") if isinstance(v, dict) else v
                        if v and not str(v).startswith("#"):
                            vns, vp = util.split_id(str(v))
                            out.append(f"{vns}:{vp}")
        return out


class IdMapper:
    def __init__(self, namespace: str, game: str, known_items: set[str],
                 tags: TagIndex):
        self.namespace = namespace
        self.game = game
        self.known = known_items
        self.tags = tags

    def map_ident(self, ident: str, allow_group: bool = True) -> tuple[Optional[str], str]:
        """Return (luanti_id_or_none, note)."""
        if ident is None:
            return None, "missing"
        if util.is_tag(ident):
            tpath = util.tag_id(ident)
            if allow_group:
                grp = tag_to_group(tpath)
                if grp:
                    return grp, ""
            members = self.tags.resolve(tpath)
            for m in members:
                mapped, _ = self.map_ident(m, allow_group=False)
                if mapped:
                    return mapped, f"tag {tpath} -> {m}"
            return None, f"unresolved tag {tpath}"
        ns, path = util.split_id(ident)
        if ns == self.namespace:
            return f"{self.namespace}:{util.lua_name(path)}", ""
        if ns == "minecraft":
            mapped = map_vanilla(path, self.game)
            if mapped:
                return mapped, ""
            return None, f"unmapped vanilla {path}"
        # other namespace: pass through namespaced
        return f"{util.lua_name(ns)}:{util.lua_name(path)}", f"external mod {ns}"


class RecipeTranslator:
    def __init__(self, fs: VirtualFS, namespace: str, mapper: IdMapper,
                 vanilla: Optional[VanillaAssets] = None, resource_root: str = ""):
        self.fs = fs
        self.namespace = namespace
        self.mapper = mapper
        self.vanilla = vanilla
        self.resource_root = resource_root or ""

    def translate_all(self) -> list[TranslatedRecipe]:
        out: list[TranslatedRecipe] = []
        markers = (
            f"data/{self.namespace}/recipes/",
            f"data/{self.namespace}/recipe/",
            f"assets/{self.namespace}/recipes/",  # legacy (1.12-)
        )
        for p in self.fs.all_paths():
            if not p.endswith(".json"):
                continue
            if not any(m in p for m in markers):
                continue
            data = self.fs.read(p)
            if not data:
                continue
            try:
                rec = util.load_json(data)
            except Exception:
                continue
            tr = self._translate_one(rec, p)
            if tr:
                out.append(tr)
        return out

    # -- individual recipe types -------------------------------------------
    def _translate_one(self, rec: dict, path: str) -> Optional[TranslatedRecipe]:
        rtype = str(rec.get("type", "")).split(":")[-1]
        handler = {
            "crafting_shaped": self._shaped,
            "crafting_shapeless": self._shapeless,
            "smelting": lambda r, p: self._cooking(r, p, "cooking"),
            "blasting": lambda r, p: self._cooking(r, p, "cooking"),
            "smoking": lambda r, p: self._cooking(r, p, "cooking"),
            "campfire_cooking": lambda r, p: self._cooking(r, p, "cooking"),
            "stonecutting": self._stonecutting,
            "smithing_transform": self._smithing,
            "crafting_special_*": lambda r, p: None,
        }.get(rtype)
        if handler is None:
            return None
        return handler(rec, path)

    def _result(self, rec: dict) -> tuple[Optional[str], int, str]:
        res = rec.get("result")
        if isinstance(res, str):
            return res, 1, ""
        if isinstance(res, dict):
            rid = res.get("item") or res.get("id") or res.get("result")
            count = int(res.get("count", 1))
            if isinstance(rid, dict):
                rid = rid.get("item") or rid.get("id")
            mapped, note = self.mapper.map_ident(rid)
            return mapped, count, note
        return None, 1, "no result"

    def _shaped(self, rec: dict, path: str) -> Optional[TranslatedRecipe]:
        pattern = rec.get("pattern") or []
        key = rec.get("key") or {}
        out_id, count, note = self._result(rec)
        if not pattern or not out_id:
            return None
        # resolve key chars -> luanti ids
        cmap: dict[str, str] = {}
        for ch, ing in key.items():
            ident = self._ing_ident(ing)
            mapped, _ = self.mapper.map_ident(ident)
            if mapped:
                cmap[ch] = mapped
        grid = []
        for row in pattern:
            grid.append([cmap.get(ch, "") for ch in row])
        grid = _trim_grid(grid)
        if not grid or not any(any(c for c in row) for row in grid):
            return None
        lua = {"output": _out(out_id, count), "recipe": grid}
        return TranslatedRecipe("shaped", lua, path, note)

    def _shapeless(self, rec: dict, path: str) -> Optional[TranslatedRecipe]:
        ingredients = rec.get("ingredients") or []
        out_id, count, note = self._result(rec)
        if not ingredients or not out_id:
            return None
        items = [self._ing_ident(i) for i in ingredients]
        if isinstance(items[0], list):  # some formats nest
            items = [x for sub in items for x in (sub if isinstance(sub, list) else [sub])]
        mapped = []
        for ident in items:
            m, _ = self.mapper.map_ident(ident)
            if m:
                mapped.append(m)
        if not mapped:
            return None
        lua = {"type": "shapeless", "output": _out(out_id, count), "recipe": mapped}
        return TranslatedRecipe("shapeless", lua, path, note)

    def _cooking(self, rec: dict, path: str, kind: str) -> Optional[TranslatedRecipe]:
        out_id, count, note = self._result(rec)
        ing = self._ing_ident(rec.get("ingredient"))
        mapped, _ = self.mapper.map_ident(ing)
        if not out_id or not mapped:
            return None
        ticks = rec.get("cookingtime", rec.get("cooktime", 200))
        seconds = max(1.0, round(float(ticks) / 20.0, 2))
        lua = {
            "type": "cooking",
            "output": _out(out_id, count),
            "recipe": mapped,
            "cooktime": seconds,
        }
        return TranslatedRecipe("cooking", lua, path, note)

    def _stonecutting(self, rec: dict, path: str) -> Optional[TranslatedRecipe]:
        out_id, count, note = self._result(rec)
        ing = self._ing_ident(rec.get("ingredient"))
        mapped, _ = self.mapper.map_ident(ing)
        if not out_id or not mapped:
            return None
        lua = {"type": "shapeless", "output": _out(out_id, count), "recipe": [mapped]}
        return TranslatedRecipe("stonecutting(approx)", lua, path,
                                "stonecutting approximated as shapeless: " + note)

    def _smithing(self, rec: dict, path: str) -> Optional[TranslatedRecipe]:
        out_id, count, note = self._result(rec)
        parts = []
        for key in ("base", "addition", "template"):
            if key in rec:
                m, _ = self.mapper.map_ident(self._ing_ident(rec[key]))
                if m and m not in parts:
                    parts.append(m)
        if not out_id or not parts:
            return None
        lua = {"type": "shapeless", "output": _out(out_id, count), "recipe": parts}
        return TranslatedRecipe("smithing(approx)", lua, path,
                                "smithing approximated as shapeless: " + note)

    @staticmethod
    def _ing_ident(ing) -> Optional[str]:
        if ing is None:
            return None
        if isinstance(ing, str):
            return ing
        if isinstance(ing, list):
            return RecipeTranslator._ing_ident(ing[0]) if ing else None
        if isinstance(ing, dict):
            for k in ("item", "id", "tag"):
                if k in ing:
                    v = ing[k]
                    if k == "tag" and not str(v).startswith("#"):
                        return "#" + str(v)
                    return str(v)
        return None


# ---------------------------------------------------------------------------
def _out(item_id: str, count: int) -> str:
    return f"{item_id} {count}" if count > 1 else item_id


def _trim_grid(grid: list[list[str]]) -> list[list[str]]:
    if not grid:
        return grid
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    # trim empty columns
    keep_cols = [c for c in range(width) if any(r[c] for r in grid)]
    if keep_cols:
        grid = [[r[c] for c in keep_cols] for r in grid]
    else:
        return []
    # trim empty rows
    grid = [r for r in grid if any(r)]
    return grid
