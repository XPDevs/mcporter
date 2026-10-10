"""
Asset pipeline: language files, textures, block/item models, sounds.

Also implements Minecraft's model inheritance (parent chains + `#texture`
references) and converts block geometry into Luanti node boxes.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import png, util
from .jarfs import VirtualFS


# ---------------------------------------------------------------------------
# Vanilla fallback source (client.jar) - provides minecraft:* models/textures
# ---------------------------------------------------------------------------
class VanillaAssets:
    def __init__(self, path: Optional[str]):
        self.fs: Optional[VirtualFS] = None
        if path and os.path.exists(path):
            try:
                self.fs = VirtualFS(path)
            except ValueError:
                self.fs = None

    def model(self, ns_path: str) -> Optional[dict]:
        if self.fs is None:
            return None
        data = self.fs.read(f"assets/minecraft/models/{ns_path}.json")
        if data is None:
            return None
        try:
            return util.load_json(data)
        except Exception:
            return None

    def texture(self, ns_path: str) -> Optional[bytes]:
        if self.fs is None:
            return None
        for ext in (".png", ".PNG"):
            data = self.fs.read(f"assets/minecraft/textures/{ns_path}{ext}")
            if data is not None:
                return data
        return None

    def tag(self, registry: str, name: str) -> Optional[dict]:
        if self.fs is None:
            return None
        for p in (f"data/minecraft/tags/{registry}/{name}.json",
                  f"data/minecraft/tags/{registry}s/{name}.json"):
            data = self.fs.read(p)
            if data is not None:
                try:
                    return util.load_json(data)
                except Exception:
                    return None
        return None


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------
@dataclass
class ResolvedModel:
    textures: dict[str, str] = field(default_factory=dict)  # symbolic -> "ns:path"
    elements: Optional[list] = None
    root_parent: str = ""
    display: dict = field(default_factory=dict)
    is_block_model: bool = True
    parents_chain: list = field(default_factory=list)


class ModelResolver:
    """Resolves MC models, following `parent` and `#texture` references."""

    def __init__(self, owner: "AssetIndex", vanilla: Optional[VanillaAssets]):
        self.owner = owner
        self.vanilla = vanilla
        self._raw_cache: dict[str, ResolvedModel] = {}
        self._res_cache: dict[str, ResolvedModel] = {}

    def _raw(self, ns: str, path: str) -> Optional[dict]:
        if ns == self.owner.namespace:
            m = self.owner.models.get(f"block/{path}") or self.owner.models.get(f"item/{path}")
            if m is not None:
                return m
            # models may be declared without category
            return self.owner.models.get(path)
        if self.vanilla is not None and ns == "minecraft":
            return self.vanilla.model(path)
        return None

    def _resolve_chain(self, ns: str, path: str, seen: set[str]) -> ResolvedModel:
        """Build the merged (but not yet #resolved) model for ns:path."""
        key = f"{ns}:{path}"
        if key in self._raw_cache:
            return self._raw_cache[key]
        if key in seen or len(seen) > 24:
            return ResolvedModel()
        seen = seen | {key}

        raw = self._raw(ns, path)
        if raw is None:
            res = ResolvedModel()
            self._raw_cache[key] = res
            return res

        res = ResolvedModel(is_block_model=path.startswith("block"))
        res.parents_chain.append(f"{ns}:{path}")
        parent = raw.get("parent")
        if parent:
            pns, ppath = util.split_id(parent)
            base = self._resolve_chain(pns, ppath, seen)
            res.textures.update(base.textures)
            res.elements = base.elements
            res.display.update(base.display)
            res.parents_chain.extend(base.parents_chain)
            if base.is_block_model is False:
                res.is_block_model = False

        # merge own textures (may contain "#ref" indirections) - NOT resolved yet
        for k, v in (raw.get("textures") or {}).items():
            res.textures[k] = v
        if "elements" in raw:
            res.elements = raw["elements"]
        if "display" in raw:
            res.display.update(raw["display"])

        self._raw_cache[key] = res
        return res

    def _follow_texture(self, value: str, table: dict, seen: set[str]) -> str:
        if not isinstance(value, str):
            return ""
        if value.startswith("#"):
            ref = value[1:]
            if ref in seen:
                return ""
            return self._follow_texture(table.get(ref, ""), table, seen | {ref})
        return value

    def resolve(self, ns: str, path: str) -> ResolvedModel:
        key = f"{ns}:{path}"
        if key in self._res_cache:
            return self._res_cache[key]
        base = self._resolve_chain(ns, path, set())
        resolved = ResolvedModel(
            elements=base.elements,
            root_parent=base.root_parent or (base.parents_chain[0] if base.parents_chain else f"{ns}:{path}"),
            display=base.display,
            is_block_model=base.is_block_model,
            parents_chain=list(base.parents_chain),
        )
        resolved.textures = {
            k: self._follow_texture(v, base.textures, set())
            for k, v in base.textures.items()
        }
        self._res_cache[key] = resolved
        return resolved


# ---------------------------------------------------------------------------
# Asset index
# ---------------------------------------------------------------------------
@dataclass
class BlockstateInfo:
    variants: dict = field(default_factory=dict)
    multipart: list = field(default_factory=list)


class AssetIndex:
    def __init__(self, fs: VirtualFS, namespace: str, vanilla: Optional[VanillaAssets] = None,
                 resource_root: str = ""):
        self.fs = fs
        self.namespace = namespace
        self.vanilla = vanilla
        self.resource_root = resource_root or ""
        self.asset_prefix = f"{self.resource_root}assets/{namespace}/"
        self.textures: dict[str, bytes] = {}
        self.models: dict[str, dict] = {}
        self.blockstates: dict[str, BlockstateInfo] = {}
        self.lang: dict[str, str] = {}
        self.all_langs: dict[str, dict[str, str]] = {}
        self.sounds: dict[str, bytes] = {}
        self.sound_events: dict = {}
        self.resolver = ModelResolver(self, vanilla)
        self._scan()

    def _scan(self) -> None:
        ns = self.namespace
        marker = f"assets/{ns}/"
        for p in self.fs.all_paths():
            idx = p.find(marker)
            if idx < 0:
                continue
            rel = p[idx + len(marker):]
            if rel.startswith("textures/") and rel.lower().endswith(".png"):
                key = rel[len("textures/"):-4]
                data = self.fs.read(p)
                if data:
                    self.textures[key] = data
            elif rel.startswith("models/") and rel.endswith(".json"):
                key = rel[len("models/"):-5]
                data = self.fs.read(p)
                if data:
                    try:
                        self.models[key] = util.load_json(data)
                    except Exception:
                        pass
            elif rel.startswith("blockstates/") and rel.endswith(".json"):
                key = rel[len("blockstates/"):-5]
                data = self.fs.read(p)
                if data:
                    try:
                        raw = util.load_json(data)
                    except Exception:
                        raw = {}
                    self.blockstates[key] = BlockstateInfo(
                        variants=raw.get("variants", {}),
                        multipart=raw.get("multipart", []),
                    )
            elif rel.startswith("lang/") and rel.endswith(".json"):
                lang = rel[len("lang/"):-5]
                data = self.fs.read(p)
                if data:
                    try:
                        table = util.load_json(data)
                    except Exception:
                        table = {}
                    if lang in ("en_us", "en_US"):
                        self.lang = table
                    self.all_langs[lang] = table
            elif rel.startswith("sounds/") and rel.lower().endswith(".ogg"):
                data = self.fs.read(p)
                if data:
                    self.sounds[rel[len("sounds/"):]] = data
            elif rel == "sounds.json":
                data = self.fs.read(p)
                if data:
                    try:
                        self.sound_events = util.load_json(data)
                    except Exception:
                        pass

    # -- texture helpers ----------------------------------------------------
    def texture_bytes(self, tex_id: str) -> Optional[bytes]:
        ns, path = util.split_id(tex_id)
        if ns == self.namespace:
            b = self.textures.get(path)
            if b:
                return b
        if self.vanilla is not None and ns == "minecraft":
            return self.vanilla.texture(path)
        # namespaced texture may have been flattened
        return self.textures.get(path)

    def texture_path_exists(self, path: str) -> bool:
        return path in self.textures

    # -- model helpers ------------------------------------------------------
    def resolve_block_model(self, name: str) -> Optional[ResolvedModel]:
        for key in (f"block/{name}", name):
            if key in self.models:
                return self.resolver.resolve(self.namespace, key)
        # via blockstate
        bs = self.blockstates.get(name)
        if bs and bs.variants:
            for variant in bs.variants.values():
                if isinstance(variant, list):
                    variant = variant[0]
                model = variant.get("model") if isinstance(variant, dict) else None
                if model:
                    ns, path = util.split_id(model)
                    return self.resolver.resolve(ns, path)
        return None

    def resolve_item_model(self, name: str) -> Optional[ResolvedModel]:
        for key in (f"item/{name}", name):
            if key in self.models:
                return self.resolver.resolve(self.namespace, key)
        # block item: models/item/foo may be absent; fall back to block model
        return None

    def lang_name(self, kind: str, path: str) -> Optional[str]:
        for key in (f"{kind}.{self.namespace}.{path}",
                    f"{kind}.{self.namespace}.{path.replace('/', '.')}",
                    f"{kind}.minecraft.{path}"):
            if key in self.lang:
                return self.lang[key]
        return None
