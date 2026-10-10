"""
Registry discovery.

Determines which blocks/items a mod defines and classifies each one.  We fuse
several independent sources of evidence:

  1. assets/<ns>/blockstates/*.json      -> definitely a block
  2. assets/<ns>/models/block/*.json     -> block model
  3. assets/<ns>/models/item/*.json      -> item model
  4. assets/<ns>/textures/{block,item}/* -> weak candidate
  5. assets/<ns>/lang/en_us.json         -> block.*/item.* display names
  6. Java bytecode string constants      -> weak candidate (compiled mods)
  7. Java source string literals         -> weak candidate (source mods)

Sources 1-5 are highly reliable; 6-7 are used to raise confidence only when
corroborated by at least one asset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import util
from .assets import AssetIndex, ResolvedModel
from .classfile import ClassFile, ClassFileError
from .jarfs import VirtualFS

# keyword tables (vanilla *material* hints, not mod names)
_WOOD = re.compile(r"(planks?|log|wood|stem|hyphae|_fence|_door|_trapdoor|_sign|_button|_pressure_plate|boat|chest_boat|_hanging_sign)")
_STONE = re.compile(r"(stone|cobble|deepslate|brick|tuff|granite|diorite|andesite|sandstone|basalt|blackstone|ore|obsidian|netherrack|end_stone|quartz)")
_DIRT = re.compile(r"(dirt|sand|gravel|clay|soul_soil|moss|mud|snow|_powder|sculk)")
_GLASS = re.compile(r"(glass|_pane)")
_LEAVES = re.compile(r"(leaves|sapling|flower|bush|grass|fern|vines|crop|wheat|carrots|potatoes|_seeds)")
_METAL = re.compile(r"(iron|gold|copper|brass|zinc|steel|tin|lead|silver|bronze|aluminum|aluminium|nickel|_ingot|_nugget|_plate|_sheet)")

_TOOLS = re.compile(r"_(sword|pickaxe|axe|shovel|hoe)$")
_ARMOR = re.compile(r"_(helmet|chestplate|leggings|boots|cap|tunic|pants)$")
_FOOD = re.compile(r"(apple|bread|cookie|cake|pie|stew|soup|jerky|cheese|meat|beef|pork|chicken|mutton|fish|cod|salmon|berry|berries|carrot|potato|beetroot|melon|banana|tomato|corn|rice|dough|bacon|sausage|chocolate|honey|milk|drink|juice|tea|coffee)")
_FOOD_NEG = re.compile(r"(cloth|block|ore|ingot|nugget|dust|plate|gear|rod|wire|brick|pane|door|trapdoor|button|sign|boat|scaffold|stick|bone|string|leather|bucket|bottle|dye|wool|carpet|slab|stairs|wall|fence|torch|lantern|seeds?$|sapling|log|planks?|_tree|leaves)")


@dataclass
class Entry:
    ident: str
    kind: str = "unknown"          # node | craftitem | tool | food
    name: str = ""
    texture: Optional[str] = None   # "ns:path" of primary texture
    tiles: dict = field(default_factory=dict)
    full_cube: bool = True
    nodebox: Optional[list] = None
    groups: dict = field(default_factory=dict)
    material: str = "stone"
    sources: set = field(default_factory=set)
    confidence: float = 0.0
    model_root: str = ""
    java_class: str = ""
    stack_max: int = 64
    drawtype: str = "normal"
    notes: list = field(default_factory=list)

    @property
    def luanti_id(self) -> str:
        return f"{self.namespace}:{self.ident}" if self.namespace else self.ident

    namespace: str = ""


class RegistryBuilder:
    def __init__(self, fs: VirtualFS, assets: AssetIndex, namespace: str):
        self.fs = fs
        self.assets = assets
        self.namespace = namespace
        self.entries: dict[str, Entry] = {}
        self.java_features: dict[str, int] = {}
        self.mixin_files: list[str] = []
        self.class_refs: set[str] = set()
        self.string_literals: set[str] = set()
        self._java_scanned = False

    # -- public -------------------------------------------------------------
    def build(self) -> dict[str, Entry]:
        blockstates = {k for k in self.assets.blockstates}
        item_models = {k[len("item/"):] for k in self.assets.models
                       if k.startswith("item/") and "/" not in k[len("item/"):]}
        block_models = {k[len("block/"):] for k in self.assets.models
                        if k.startswith("block/") and "/" not in k[len("block/"):]}
        lang_blocks = set()
        lang_items = set()
        for key in self.assets.lang:
            if key.startswith("block."):
                ns, name = util.split_id(key[len("block."):])
                if ns == self.namespace and "/" not in name:
                    lang_blocks.add(name)
            elif key.startswith("item."):
                ns, name = util.split_id(key[len("item."):])
                if ns == self.namespace and "/" not in name:
                    lang_items.add(name)

        has_blockstates = bool(blockstates)

        # 1. blockstates are the authoritative block list
        for name in blockstates:
            e = self._ensure(name)
            e.sources.add("blockstate")
            e.kind = "node"

        # 2. item models define items (unless the name is a known block)
        for name in item_models:
            if name in blockstates:
                continue  # block item
            e = self._ensure(name)
            e.sources.add("item_model")
            if name in block_models or name in lang_blocks:
                e.kind = "node"
            elif e.kind == "unknown":
                e.kind = "craftitem"

        # 3. block models corroborated by an item model / block lang are blocks;
        #    otherwise they are likely sub-models/variants and are skipped
        #    (unless the mod has no blockstates directory at all).
        for name in block_models:
            if name in blockstates:
                continue
            corroborated = name in item_models or name in lang_blocks
            if corroborated or not has_blockstates:
                e = self._ensure(name)
                e.sources.add("block_model")
                e.kind = "node"

        # 4. annotations from textures (only existing entries)
        self._from_textures()

        # 5. language entries (weak, but catch model-less content)
        self._from_lang()

        # 6. java bytecode corroboration
        self._from_java()

        self._finalize()
        return self.entries

    # -- source passes ------------------------------------------------------
    def _ensure(self, ident: str) -> Entry:
        e = self.entries.get(ident)
        if e is None:
            e = Entry(ident=ident, namespace=self.namespace)
            self.entries[ident] = e
        return e

    def _from_blockstates(self) -> None:
        for name in self.assets.blockstates:
            e = self._ensure(name)
            e.sources.add("blockstate")
            e.kind = "node"

    def _from_block_models(self) -> None:
        for key in self.assets.models:
            if key.startswith("block/"):
                name = key[len("block/"):]
                if "/" in name:
                    continue
                e = self._ensure(name)
                e.sources.add("block_model")
                if e.kind == "unknown":
                    e.kind = "node"

    def _from_item_models(self) -> None:
        for key in self.assets.models:
            if key.startswith("item/"):
                name = key[len("item/"):]
                if "/" in name:
                    continue
                e = self._ensure(name)
                e.sources.add("item_model")
                if e.kind == "unknown":
                    e.kind = "craftitem"

    def _from_textures(self) -> None:
        # Textures alone are NOT sufficient evidence of a registry entry: mods
        # ship many helper/overlay textures.  Only annotate existing entries.
        for key in self.assets.textures:
            if key.startswith("block/"):
                e = self.entries.get(key[len("block/"):])
                if e is not None:
                    e.sources.add("block_texture")
            elif key.startswith("item/"):
                e = self.entries.get(key[len("item/"):])
                if e is not None:
                    e.sources.add("item_texture")

    def _from_lang(self) -> None:
        for key, value in self.assets.lang.items():
            for prefix, kind in (("block.", "node"), ("item.", "craftitem")):
                if key.startswith(prefix):
                    rest = key[len(prefix):]
                    ns, name = util.split_id(rest)
                    if ns != self.namespace:
                        continue
                    if "/" in name:
                        continue
                    e = self._ensure(name)
                    e.sources.add("lang")
                    e.name = e.name or value
                    if e.kind == "unknown":
                        e.kind = kind
                    # block.* wins over item.* for classification
                    if prefix == "block.":
                        e.kind = "node"
                    break

    def _from_java(self) -> None:
        self._scan_java()
        # only use bytecode ids that are corroborated by an asset source
        for lit in self.string_literals:
            if not _plausible_id(lit):
                continue
            e = self.entries.get(lit)
            if e is not None and e.sources & {"block_model", "item_model", "lang",
                                              "blockstate", "block_texture", "item_texture"}:
                e.sources.add("bytecode")

    # -- java scanning ------------------------------------------------------
    def _scan_java(self) -> None:
        if self._java_scanned:
            return
        self._java_scanned = True

        class_paths = self.fs.glob("", ".class")
        # For source trees, read .java for package/class + string literals.
        java_paths = self.fs.glob("", ".java")

        for p in class_paths[:8000]:
            data = self.fs.read(p)
            if not data:
                continue
            try:
                cf = ClassFile(data, p)
            except (ClassFileError, Exception):
                continue
            self.class_refs.update(cf.class_refs)
            for s in cf.strings:
                self.string_literals.add(s)
            self._feature_scan_class(cf)

        for p in java_paths[:8000]:
            text = self.fs.text(p) or ""
            for m in re.finditer(r'"([a-z0-9_]{3,40})"', text):
                self.string_literals.add(m.group(1))
            path_lits = re.findall(r'new ResourceLocation\(\s*"([^"]+)"\s*,\s*"([^"]+)"', text)
            for ns, name in path_lits:
                if ns == self.namespace:
                    self.string_literals.add(name)
            self._feature_scan_source(text)

        # mixin configs
        for p in self.fs.all_paths():
            if p.endswith(".mixins.json"):
                self.mixin_files.append(p)

    def _feature_scan_class(self, cf: ClassFile) -> None:
        refs = " ".join(cf.class_refs)
        def bump(feature: str) -> None:
            self.java_features[feature] = self.java_features.get(feature, 0) + 1

        if "mixins" in refs or "spongepowered.asm.mixin" in refs:
            bump("mixin")
        if "world.entity" in refs or "world.entity.Entity" in refs:
            bump("entity")
        if "BlockEntity" in refs or "block.entity" in refs:
            bump("block_entity")
        if "gui" in refs and "client" in refs:
            bump("gui")
        if "client.renderer" in refs or "client.render" in refs:
            bump("client_render")
        if "network" in refs and ("Packet" in refs or "payload" in refs.lower()):
            bump("networking")
        if "Fluid" in refs:
            bump("fluid")
        if "Capabilit" in refs or "IEnergyStorage" in refs:
            bump("capability")
        if "Menu" in refs or "AbstractContainerMenu" in refs:
            bump("container_menu")
        if "datafixer" in refs.lower() or "Codec" in refs:
            bump("codec")
        # block/item subclasses
        for parent in ("Block", "Item", "BlockItem", "SwordItem", "PickaxeItem",
                       "AxeItem", "ShovelItem", "HoeItem", "ArmorItem",
                       "BlockEntity", "LivingEntity", "Mob", "Entity", "Fluid",
                       "CreativeModeTab", "Enchantment", "Potion", "Effect"):
            if cf.super_class.endswith("." + parent) or cf.super_class == parent:
                bump("extends_" + parent)

    def _feature_scan_source(self, text: str) -> None:
        def bump(feature: str) -> None:
            self.java_features[feature] = self.java_features.get(feature, 0) + 1

        low = text.lower()
        if "@mixin" in low or "spongepowered.asm.mixin" in low:
            bump("mixin")
        if "net.minecraft.world.entity" in low and "extends" in low:
            bump("entity")
        if "blockentity" in low:
            bump("block_entity")
        if "abstractcontainerscreen" in low or "net.minecraft.client.gui.screens" in low:
            bump("gui")
        if "blockentityrenderer" in low or "entityrenderer" in low or "client.renderer" in low:
            bump("client_render")
        if "custompayload" in low or "packet" in low and "network" in low:
            bump("networking")
        if re.search(r"\bextends\s+Fluid\b", text):
            bump("fluid")
        if "capabilit" in low or "ienergystorage" in low:
            bump("capability")
        if "abstractcontainermenu" in low or re.search(r"\bextends\s+\w*Menu\b", text):
            bump("container_menu")
        if "datapack" in low or "MapCodec" in text or "RecordCodecBuilder" in text:
            bump("codec")
        # superclass / interface targets
        for m in re.finditer(r"\bclass\s+\w+\s+extends\s+([\w.]+)", text):
            base = m.group(1).split(".")[-1]
            bump("extends_" + base)
        for m in re.finditer(r"\bimplements\s+([\w.,\s]+?)(?:\{|$)", text):
            for iface in m.group(1).split(","):
                name = iface.strip().split(".")[-1].split("<")[0].strip()
                if name:
                    bump("implements_" + name)

    # -- finalize -----------------------------------------------------------
    def _finalize(self) -> None:
        for ident, e in list(self.entries.items()):
            # skip obvious non-content
            if ident in ("air", "debug", "missingno", "pack", "icon", "logo", "icon_16x16"):
                del self.entries[ident]
                continue
            strong = e.sources & {"block_model", "item_model", "lang", "blockstate"}
            if not strong and not (e.sources & {"block_texture", "item_texture"}):
                del self.entries[ident]
                continue
            self._classify(e)
            self._resolve_visual(e)
            self._assign_groups(e)
            self._score(e)

    def _classify(self, e: Entry) -> None:
        if _TOOLS.search(e.ident):
            e.kind = "tool"
        elif _ARMOR.search(e.ident):
            e.kind = "tool"
        elif e.kind == "craftitem" and _FOOD.search(e.ident) and not _FOOD_NEG.search(e.ident):
            e.kind = "food"
        # block texture + no item model still node; item model only => item
        if "blockstate" in e.sources or "block_model" in e.sources:
            e.kind = "node"

    def _resolve_visual(self, e: Entry) -> None:
        rm: Optional[ResolvedModel] = None
        if e.kind == "node":
            rm = self.assets.resolve_block_model(e.ident)
        if rm is None:
            rm = self.assets.resolve_item_model(e.ident)
        if rm is None:
            rm = self.assets.resolve_block_model(e.ident)
        if rm is None:
            return
        e.model_root = rm.root_parent

        # gather concrete texture ids in a stable order
        face_tex = _faces_from_model(rm)
        e.tiles = face_tex
        # primary texture
        for key in ("all", "side", "north", "texture", "layer0", "particle", "top"):
            if key in rm.textures and rm.textures[key]:
                e.texture = rm.textures[key]
                break
        if e.texture is None:
            for v in rm.textures.values():
                if v:
                    e.texture = v
                    break

        # full cube detection
        chain = " ".join(rm.parents_chain)
        base_names = {p.split(":")[-1].split("/")[-1] for p in rm.parents_chain}
        if any("cross" in b or "crop" in b or b in ("flower", "sapling", "grass", "vine") for b in base_names):
            e.drawtype = "plantlike"
            e.full_cube = False
            return
        is_cube_root = ("cube" in chain) or any(
            p.split(":")[-1].split("/")[-1] in ("block", "orientable", "column", "directional")
            for p in rm.parents_chain
        )
        if rm.elements:
            e.full_cube = _is_full_cube(rm.elements)
            if not e.full_cube:
                e.nodebox = _nodebox_from_elements(rm.elements)
        else:
            e.full_cube = bool(is_cube_root)

    def _assign_groups(self, e: Entry) -> None:
        n = e.ident
        if _WOOD.search(n):
            e.material = "wood"
            e.groups = {"choppy": 2}
        elif _GLASS.search(n):
            e.material = "glass"
            e.groups = {"cracky": 2, "glass": 1}
        elif _LEAVES.search(n):
            e.material = "plant"
            e.groups = {"snappy": 2, "dig_immediate": 1 if "grass" in n else 0}
            e.groups = {k: v for k, v in e.groups.items() if v or k != "dig_immediate"}
        elif _DIRT.search(n):
            e.material = "dirt"
            e.groups = {"crumbly": 3}
        elif _METAL.search(n):
            e.material = "metal"
            e.groups = {"cracky": 2, "metal": 1}
        elif _STONE.search(n):
            e.material = "stone"
            e.groups = {"cracky": 3, "stone": 1}
        else:
            e.material = "stone"
            e.groups = {"cracky": 3}
        if e.kind == "node":
            e.groups.setdefault("is_ground_content", 0)
            if _STONE.search(n) or _DIRT.search(n):
                e.groups["is_ground_content"] = 1

    def _score(self, e: Entry) -> None:
        s = e.sources
        score = 0.0
        if "blockstate" in s:
            score += 0.35
        if "block_model" in s:
            score += 0.25
        if "item_model" in s:
            score += 0.25
        if "lang" in s:
            score += 0.2
        if "block_texture" in s or "item_texture" in s:
            score += 0.15
        if "bytecode" in s:
            score += 0.1
        if e.name:
            score += 0.05
        if e.texture:
            score += 0.1
        e.confidence = min(1.0, score)

    # -- stats for the report ----------------------------------------------
    def stats(self) -> dict:
        kinds: dict[str, int] = {}
        for e in self.entries.values():
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        return {"total": len(self.entries), "kinds": kinds}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _plausible_id(s: str) -> bool:
    if not s or len(s) < 3 or len(s) > 48:
        return False
    if s.startswith(("java.", "net.minecraft", "org.", "com.", "net.")):
        return False
    return bool(re.fullmatch(r"[a-z0-9_]+", s)) and "_" in s or s.islower()


def _faces_from_model(rm: ResolvedModel) -> dict:
    """Map Luanti tile slots to texture ids where possible."""
    t = rm.textures
    if t.get("all"):
        return {"all": t["all"]}
    out: dict[str, str] = {}
    # MC uses up/down; Luanti uses top/bottom
    for src, dst in (("up", "top"), ("down", "bottom"), ("top", "top"), ("bottom", "bottom"),
                     ("north", "north"), ("south", "south"), ("east", "east"), ("west", "west")):
        if t.get(src):
            out[dst] = t[src]
    if t.get("side"):
        for face in ("north", "south", "east", "west"):
            out.setdefault(face, t["side"])
    if t.get("end"):
        out.setdefault("top", t["end"])
        out.setdefault("bottom", t["end"])
    if t.get("front"):
        out["north"] = t["front"]
    if not out and t.get("layer0"):
        out["all"] = t["layer0"]
    return out


def _is_full_cube(elements: list) -> bool:
    if not elements:
        return False
    mn = [16.0, 16.0, 16.0]
    mx = [0.0, 0.0, 0.0]
    for el in elements:
        f = el.get("from", [0, 0, 0])
        to = el.get("to", [0, 0, 0])
        for i in range(3):
            mn[i] = min(mn[i], f[i])
            mx[i] = max(mx[i], to[i])
    return all(abs(mn[i]) < 0.01 and abs(mx[i] - 16) < 0.01 for i in range(3))


def _nodebox_from_elements(elements: list) -> list:
    """Approximate a model by its overall bounding box (Luanti coordinates)."""
    mn = [16.0, 16.0, 16.0]
    mx = [0.0, 0.0, 0.0]
    for el in elements:
        f = el.get("from", [0, 0, 0])
        to = el.get("to", [0, 0, 0])
        for i in range(3):
            mn[i] = min(mn[i], f[i])
            mx[i] = max(mx[i], to[i])
    # MC: x east, y up, z south; Luanti: x east, y up, z north -> flip z
    x1 = (mn[0] - 8) / 16
    y1 = (mn[1] - 8) / 16
    z1 = (8 - mx[2]) / 16
    x2 = (mx[0] - 8) / 16
    y2 = (mx[1] - 8) / 16
    z2 = (8 - mn[2]) / 16
    return [{"x1": round(x1, 4), "y1": round(y1, 4), "z1": round(z1, 4),
             "x2": round(x2, 4), "y2": round(y2, 4), "z2": round(z2, 4)}]
