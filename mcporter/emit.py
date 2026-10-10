"""
Lua / game-content emitter.

Turns the analysed model (entries, recipes, loot, assets) into a complete,
loadable Luanti mod directory.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from . import png, util
from .assets import AssetIndex
from .detect import ModInfo
from .registry import Entry
from .recipes import TranslatedRecipe

GAMES = {
    "voxelibre": {
        "optional_depends": "mcl_core, mcl_sounds, mcl_util",
        "desc_suffix": " (Minecraft port)",
        "translation": True,
    },
    "mtg": {
        "optional_depends": "default",
        "desc_suffix": "",
        "translation": True,
    },
}

_SOUND_KIND = {
    "stone": "stone", "metal": "metal", "wood": "wood", "dirt": "dirt",
    "glass": "glass", "plant": "grass", "sand": "sand", "snow": "snow",
    "cloth": "cloth", "gravel": "gravel", "water": "water",
    "leaves": "leaves",
}

_TOOL_MATERIALS = {
    "wooden": {"cap": "crumbly", "level": 1, "uses": 60, "speed": 2.0, "dmg": 1},
    "stone": {"cap": "cracky", "level": 1, "uses": 132, "speed": 4.0, "dmg": 2},
    "iron": {"cap": "cracky", "level": 2, "uses": 251, "speed": 6.0, "dmg": 3},
    "gold": {"cap": "cracky", "level": 1, "uses": 33, "speed": 12.0, "dmg": 1},
    "diamond": {"cap": "cracky", "level": 3, "uses": 1562, "speed": 8.0, "dmg": 4},
    "netherite": {"cap": "cracky", "level": 4, "uses": 2031, "speed": 9.0, "dmg": 5},
    "copper": {"cap": "cracky", "level": 2, "uses": 190, "speed": 5.0, "dmg": 2},
    "brass": {"cap": "cracky", "level": 2, "uses": 300, "speed": 6.0, "dmg": 2},
    "steel": {"cap": "cracky", "level": 2, "uses": 251, "speed": 6.0, "dmg": 3},
    "zinc": {"cap": "cracky", "level": 2, "uses": 200, "speed": 5.0, "dmg": 2},
    "bronze": {"cap": "cracky", "level": 2, "uses": 220, "speed": 5.0, "dmg": 2},
}


@dataclass
class TexturePlan:
    files: dict[str, bytes] = field(default_factory=dict)   # filename -> png bytes
    by_tex_id: dict[str, str] = field(default_factory=dict)  # "ns:path" -> filename
    missing: list[str] = field(default_factory=list)


class Emitter:
    def __init__(self, outdir: str, info: ModInfo, entries: dict[str, Entry],
                 recipes: list[TranslatedRecipe], loot: dict[str, str],
                 assets: AssetIndex, game: str = "voxelibre",
                 vanilla=None, logic: Optional[dict] = None,
                 j2l_stats=None):
        self.outdir = outdir
        self.info = info
        self.entries = entries
        self.recipes = recipes
        self.loot = loot
        self.assets = assets
        self.game = game if game in GAMES else "voxelibre"
        self.vanilla = vanilla
        self.logic = logic or {}
        self.j2l_stats = j2l_stats
        self.ns = util.lua_name(info.namespace)
        self.texplan = TexturePlan()
        self.notes: list[str] = []
        self._placeholder_cache: Optional[bytes] = None

    # -- public -------------------------------------------------------------
    def emit(self) -> dict:
        util.ensure_dir(self.outdir)
        util.ensure_dir(os.path.join(self.outdir, "textures"))
        used = self._plan_textures()
        self._write_textures()
        self._write_sounds()
        self._write_mod_conf()
        self._write_ported()
        self._write_logic()
        self._write_init()
        self._write_blocks()
        self._write_items()
        self._write_recipes()
        self._write_locales()
        stats = {
            "textures_written": len(self.texplan.files),
            "missing_textures": self.texplan.missing,
            "nodes": sum(1 for e in self.entries.values() if e.kind == "node"),
            "items": sum(1 for e in self.entries.values() if e.kind in ("craftitem", "tool", "food")),
            "logic_files": len(self.logic),
        }
        return stats

    # -- texture planning ---------------------------------------------------
    def _plan_textures(self) -> None:
        for e in self.entries.values():
            if e.kind == "node":
                # collect node textures
                tex_ids = []
                if e.tiles:
                    tex_ids = [t for t in e.tiles.values() if t]
                if e.texture:
                    tex_ids.append(e.texture)
                for tid in dict.fromkeys(tex_ids):
                    self._ensure_texture(tid)
                # inventory image fallback
                if e.texture:
                    e_texture_file = self.texplan.by_tex_id.get(e.texture)
            else:
                self._plan_item_texture(e)

    def _plan_item_texture(self, e: Entry) -> None:
        rm = self.assets.resolve_item_model(e.ident)
        layers: list[str] = []
        if rm:
            # collect layer0..N in order
            for i in range(8):
                key = f"layer{i}"
                if key in rm.textures and rm.textures[key]:
                    layers.append(rm.textures[key])
        if not layers and e.texture:
            layers.append(e.texture)
        if not layers:
            return
        # resolve each layer to bytes
        layer_bytes = []
        for lid in layers:
            b = self.assets.texture_bytes(lid)
            if b:
                layer_bytes.append(b)
        if not layer_bytes:
            self.texplan.missing.extend(layers)
            return
        key = f"{self.ns}_{util.lua_name(e.ident)}"
        filename = key + ".png"
        if len(layer_bytes) == 1:
            self.texplan.files[filename] = layer_bytes[0]
        else:
            comp = png.composite_layers(layer_bytes)
            self.texplan.files[filename] = comp if comp else layer_bytes[0]
        e.texture = f"{self.ns}:{e.ident}"  # mark: use dedicated file
        e.tiles["__file__"] = filename

    def _ensure_texture(self, tid: str) -> Optional[str]:
        if tid in self.texplan.by_tex_id:
            return self.texplan.by_tex_id[tid]
        ns, path = util.split_id(tid)
        if ns == self.ns:
            filename = f"{self.ns}_{util.lua_name(path)}.png"
        else:
            filename = f"{ns}_{util.lua_name(path)}.png"
        data = self.assets.texture_bytes(tid)
        if data is None:
            # try to locate a same-named texture under the mod namespace
            data = self.assets.textures.get(path)
        if data is None:
            data = self._placeholder()
            self.notes.append(f"missing texture for {tid}; generated placeholder")
            self.texplan.missing.append(tid)
        self.texplan.files[filename] = data
        self.texplan.by_tex_id[tid] = filename
        return filename

    def _placeholder(self) -> bytes:
        if self._placeholder_cache is None:
            w = h = 16
            px = bytearray(w * h * 4)
            for y in range(h):
                for x in range(w):
                    on = ((x // 4) + (y // 4)) % 2 == 0
                    i = (y * w + x) * 4
                    px[i] = 255 if on else 30
                    px[i + 1] = 30
                    px[i + 2] = 255 if on else 30
                    px[i + 3] = 255
            self._placeholder_cache = png.encode(png.Image(w, h, px))
        return self._placeholder_cache

    def _texture_ref(self, tid: str) -> Optional[str]:
        return self.texplan.by_tex_id.get(tid)

    def _write_textures(self) -> None:
        tdir = os.path.join(self.outdir, "textures")
        for name, data in self.texplan.files.items():
            with open(os.path.join(tdir, name), "wb") as fh:
                fh.write(data)
        # always provide the placeholder referenced by texture-less nodes/items
        ph = os.path.join(tdir, "mcporter_placeholder.png")
        if not os.path.exists(ph):
            with open(ph, "wb") as fh:
                fh.write(self._placeholder())

    def _write_sounds(self) -> None:
        if not self.assets.sounds:
            return
        sdir = util.ensure_dir(os.path.join(self.outdir, "sounds"))
        count = 0
        for rel, data in self.assets.sounds.items():
            name = f"{self.ns}_{util.lua_name(rel[:-4])}.ogg"
            with open(os.path.join(sdir, name), "wb") as fh:
                fh.write(data)
            count += 1
        if count:
            self.notes.append(
                f"copied {count} sound file(s) into sounds/ (filenames prefixed with "
                f"'{self.ns}_'); mapping block events to sounds requires manual wiring")

    def _write_logic(self) -> None:
        if not self.logic:
            return
        for rel, src in self.logic.items():
            self._write(rel, src)
        # a self-contained loader so init.lua can pull the whole tree in
        names = sorted(self.logic)
        loader = [
            "-- loads every translated Java class (best-effort reference Lua).",
            "-- Failures are ignored: the static content port does not depend on",
            "-- this logic being runnable.",
            "",
            'local _mp = core.get_modpath(core.get_current_modname()) or "."',
        ]
        for rel in names:
            base = rel.split("/", 1)[1][:-4]
            loader.append(f'pcall(dofile, _mp .. "/logic/{base}.lua")')
        self._write("logic/init.lua", "\n".join(loader) + "\n")
        st = self.j2l_stats
        if st is not None:
            self.notes.append(
                f"translated {st.translated_methods}/{st.methods} Java methods "
                f"from {st.classes} classes into Lua (best-effort reference; see logic/)")
        else:
            self.notes.append(f"generated {len(names)} Java->Lua reference file(s) in logic/")

    def _write_mod_conf(self) -> None:
        cfg = GAMES[self.game]
        deps = cfg["optional_depends"]
        title = self.info.name.replace("\n", " ")
        desc = (self.info.description or f"Ported from Minecraft: {title}").replace("\n", " ")
        lines = [
            f"name = {self.ns}",
            f"title = {title}{cfg['desc_suffix']}",
            f"description = {desc[:250]}",
            f"optional_depends = {deps}",
            "min_minetest_version = 5.4",
        ]
        self._write("mod.conf", "\n".join(lines) + "\n")

    def _write_ported(self) -> None:
        lua = f'''-- Generated by mcporter {self._version()} from "{self.info.name}" ({self.info.loader})
-- Shared helpers for the ported mod.

ported = {{}}
ported.is_voxelibre = core.get_modpath("mcl_core") ~= nil
ported.is_mtg = core.get_modpath("default") ~= nil
ported.mod = {util.lua_quote(self.ns)}

-- Modern translation API (Luanti >= 5.4). core.translate() itself now expects
-- (textdomain, str), so we bind the mod's textdomain once.
if core.get_translator then
    ported.S = core.get_translator({util.lua_quote(self.ns)})
else
    ported.S = function(s) return s end
end

function ported.snd(kind)
    kind = kind or "stone"
    local prefix = "node_sound_" .. kind .. "_defaults"
    local f
    if ported.is_voxelibre and mcl_sounds then f = mcl_sounds[prefix]
    elseif ported.is_mtg and default then f = default[prefix] end
    if not f then
        f = (ported.is_voxelibre and mcl_sounds and mcl_sounds.node_sound_stone_defaults)
            or (default and default.node_sound_stone_defaults)
    end
    if f then return f() end
    return {{}}
end

function ported.eat(itemstack, user, sat, heal)
    if ported.is_voxelibre and mcl_hunger and mcl_hunger.item_eat then
        local st = mcl_hunger.item_eat(sat or 1)(itemstack, user)
        return st
    elseif ported.is_mtg and default and default.item_eat then
        return default.item_eat(heal or 1)(itemstack, user)
    end
    return itemstack
end
'''
        self._write("ported.lua", lua)

    def _write_init(self) -> None:
        ns_prefix = util.lua_quote(self.ns + ":")
        logic_line = ('if true then pcall(dofile, modpath .. "/logic/init.lua") end'
                      if self.logic
                      else '-- (no compiled Java bytecode was present to translate)')
        lua = f'''--[[
    {self.info.name}
    Automatically ported from a Minecraft mod by mcporter {self._version()}.

    Source loader : {self.info.loader}
    Source mod id : {self.info.modid}
    Source version: {self.info.version}
    Target game   : {self.game}

    NOTE: this is a *static* translation. Gameplay logic that lives in Java
    (machines, entities, GUIs, rendering, networking) cannot be recreated
    automatically and has been reported in TRANSLATION_REPORT.md.
]]

local modpath = core.get_modpath({util.lua_quote(self.ns)})

dofile(modpath .. "/ported.lua")
dofile(modpath .. "/blocks.lua")
dofile(modpath .. "/items.lua")
dofile(modpath .. "/recipes.lua")

{logic_line}

local function ported_count(t)
    local prefix = {ns_prefix}
    local n = 0
    for k in pairs(t) do
        if type(k) == "string" and k:sub(1, #prefix) == prefix then n = n + 1 end
    end
    return n
end

core.log("[{self.ns}] registered " .. ported_count(core.registered_nodes) .. " nodes / "
    .. ported_count(core.registered_craftitems) .. " craftitems (ported from {self.info.modid})")
'''
        self._write("init.lua", lua)

    def _write_blocks(self) -> None:
        out = [self._header("Nodes (blocks)")]
        for e in sorted(self.entries.values(), key=lambda x: x.ident):
            if e.kind != "node":
                continue
            out.append(self._node_def(e))
        self._write("blocks.lua", "\n".join(out) + "\n")

    def _write_items(self) -> None:
        out = [self._header("Items (craftitems, tools, food)")]
        for e in sorted(self.entries.values(), key=lambda x: x.ident):
            if e.kind == "node":
                continue
            if e.kind == "tool":
                out.append(self._tool_def(e))
            elif e.kind == "food":
                out.append(self._food_def(e))
            else:
                out.append(self._craftitem_def(e))
        self._write("items.lua", "\n".join(out) + "\n")

    def _node_def(self, e: Entry) -> str:
        luanti_id = f"{self.ns}:{e.ident}"
        desc = e.name or util.titleize(e.ident)
        tiles = self._node_tiles(e)
        groups = {k: v for k, v in e.groups.items() if k != "is_ground_content"}
        ground = "true" if e.groups.get("is_ground_content") else "false"
        kind = _SOUND_KIND.get(e.material, "stone")
        lines = [f"core.register_node({util.lua_quote(luanti_id)}, {{"]
        lines.append(f"    description = ported.S({util.lua_quote(desc)}),")
        lines.append(f"    tiles = {tiles},")
        lines.append(f"    groups = {_ftable(groups)},")
        lines.append(f"    is_ground_content = {ground},")
        if e.material in ("glass",):
            lines.append('    paramtype = "light",')
            lines.append("    sunlight_propagates = true,")
        if e.drawtype == "plantlike":
            lines.append('    drawtype = "plantlike",')
            lines.append('    paramtype = "light",')
            lines.append("    walkable = false,")
        elif e.drawtype == "nodebox" or (not e.full_cube and e.nodebox):
            lines.append('    drawtype = "nodebox",')
            lines.append(f"    node_box = {_nodebox(e.nodebox or [{'x1':-0.5,'y1':-0.5,'z1':-0.5,'x2':0.5,'y2':0.5,'z2':0.5}])},")
            lines.append(f"    selection_box = {_nodebox(e.nodebox or [{'x1':-0.5,'y1':-0.5,'z1':-0.5,'x2':0.5,'y2':0.5,'z2':0.5}])},")
        if e.material == "plant" and e.drawtype != "plantlike":
            lines.append('    paramtype = "light",')
        drop = self.loot.get(e.ident)
        if drop and drop != luanti_id:
            lines.append(f"    drop = {util.lua_quote(drop)},")
        lines.append(f"    sounds = ported.snd({util.lua_quote(kind)}),")
        lines.append("})")
        return "\n".join(lines) + "\n"

    def _node_tiles(self, e: Entry) -> str:
        if "__file__" in e.tiles:
            return _ftable_str([e.tiles["__file__"]])
        refs: list[str] = []
        if e.tiles:
            # map face order to Luanti tile order: top,bottom,right,left,back,front
            face_map = {"all": None, "top": 0, "bottom": 1, "side": None,
                        "north": 5, "south": 4, "east": 2, "west": 3,
                        "up": 0, "down": 1, "front": None}
            slots: list[Optional[str]] = [None] * 6
            all_tex = e.tiles.get("all")
            if all_tex:
                f = self._texture_ref(all_tex)
                return _ftable_str([f or "mcporter_placeholder.png"])
            for face, tid in e.tiles.items():
                idx = face_map.get(face)
                if idx is None or not tid:
                    continue
                f = self._texture_ref(tid)
                if f:
                    slots[idx] = f
            # fill missing faces with first available
            first = next((s for s in slots if s), None)
            slots = [s or first or "mcporter_placeholder.png" for s in slots]
            if len(set(slots)) == 1:
                return _ftable_str([slots[0]])
            return _ftable_str(slots)
        if e.texture:
            f = self._texture_ref(e.texture)
            if f:
                return _ftable_str([f])
        return '{"mcporter_placeholder.png"}'

    def _craftitem_def(self, e: Entry) -> str:
        luanti_id = f"{self.ns}:{e.ident}"
        desc = e.name or util.titleize(e.ident)
        img = self._item_image(e)
        return (
            f"core.register_craftitem({util.lua_quote(luanti_id)}, {{\n"
            f"    description = ported.S({util.lua_quote(desc)}),\n"
            f"    inventory_image = {util.lua_quote(img)},\n"
            f"    stack_max = {e.stack_max},\n"
            f"}})\n"
        )

    def _food_def(self, e: Entry) -> str:
        luanti_id = f"{self.ns}:{e.ident}"
        desc = e.name or util.titleize(e.ident)
        img = self._item_image(e)
        return (
            f"core.register_craftitem({util.lua_quote(luanti_id)}, {{\n"
            f"    description = ported.S({util.lua_quote(desc)}),\n"
            f"    inventory_image = {util.lua_quote(img)},\n"
            f"    stack_max = {e.stack_max},\n"
            f"    groups = {{food = 4}},\n"
            f"    _mcl_saturation = 2.4,\n"
            f"    on_use = function(itemstack, user, pointed_thing)\n"
            f"        ported.eat(itemstack, user, 4, 3)\n"
            f"    end,\n"
            f"}})\n"
        )

    def _tool_def(self, e: Entry) -> str:
        luanti_id = f"{self.ns}:{e.ident}"
        desc = e.name or util.titleize(e.ident)
        img = self._item_image(e)
        mat, tool = _tool_kind(e.ident)
        m = _TOOL_MATERIALS.get(mat, _TOOL_MATERIALS["iron"])
        if tool == "sword":
            groupcaps = "{}"
            damage = m["dmg"] + 2
            lines = [
                f"core.register_tool({util.lua_quote(luanti_id)}, {{",
                f"    description = ported.S({util.lua_quote(desc)}),",
                f"    inventory_image = {util.lua_quote(img)},",
                "    tool_capabilities = {",
                f"        full_punch_interval = 0.8,",
                f"        groupcaps = {{ snappy = {{times={{0.4}}, uses={m['uses']}}} }},",
                f"        damage_groups = {{fleshy={damage}}},",
                "    },",
                "})",
            ]
        else:
            cap = m["cap"]
            lines = [
                f"core.register_tool({util.lua_quote(luanti_id)}, {{",
                f"    description = ported.S({util.lua_quote(desc)}),",
                f"    inventory_image = {util.lua_quote(img)},",
                "    tool_capabilities = {",
                f"        full_punch_interval = 0.9,",
                f"        max_drop_level = {m['level']},",
                f"        groupcaps = {{",
                f"            {cap} = {{times={{0.4, 0.25, 0.15}}, uses={m['uses']}}},",
                "        },",
                f"        damage_groups = {{fleshy={m['dmg'] + 1}}},",
                "    },",
                "})",
            ]
        return "\n".join(lines) + "\n"

    def _item_image(self, e: Entry) -> str:
        if e.tiles.get("__file__"):
            return e.tiles["__file__"]
        # node-derived item image
        if e.texture:
            ref = self._texture_ref(e.texture)
            if ref:
                return ref
        if e.tiles:
            first = next((t for t in e.tiles.values() if t and not t.startswith("__")), None)
            if first:
                ref = self._texture_ref(first)
                if ref:
                    return ref
        return "mcporter_placeholder.png"

    # -- recipes ------------------------------------------------------------
    def _write_recipes(self) -> None:
        out = [self._header("Recipes")]
        if not self.recipes:
            out.append("-- (no data-driven recipes were found for this mod)")
        for tr in self.recipes:
            if tr.note:
                out.append(f"-- note: {tr.note}")
            try:
                out.append(f"core.register_craft({_lua_value(tr.lua)})")
            except Exception:
                continue
        self._write("recipes.lua", "\n".join(out) + "\n")

    # -- locales ------------------------------------------------------------
    def _write_locales(self) -> None:
        if not GAMES[self.game].get("translation", True):
            return
        if not self.assets.all_langs:
            return
        ldir = util.ensure_dir(os.path.join(self.outdir, "locale"))
        en = self.assets.lang
        written = 0
        for lang, table in self.assets.all_langs.items():
            if lang in ("en_us", "en_US"):
                continue
            lines = [f"# textdomain {self.ns}", ""]
            seen: set[str] = set()
            for key, value in table.items():
                if not (key.startswith("block.") or key.startswith("item.")):
                    continue
                src = en.get(key)
                if not src or src == value or src in seen:
                    continue
                seen.add(src)
                lines.append(f"{_tr_escape(src)} = {_tr_escape(value)}")
            if len(lines) > 2:
                self._write(os.path.join("locale", f"{lang}.tr"), "\n".join(lines) + "\n")
                written += 1
        self.notes.append(f"generated {written} locale translation file(s)")

    # -- helpers ------------------------------------------------------------
    def _header(self, title: str) -> str:
        return (f"--[[\n    {self.info.name} - {title}\n"
                f"    Generated by mcporter {self._version()}.\n"
                f"--]]\n")

    def _version(self) -> str:
        from . import __version__
        return __version__

    def _write(self, rel: str, content: str) -> None:
        path = os.path.join(self.outdir, rel)
        util.ensure_dir(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)


# ---------------------------------------------------------------------------
# Lua literal formatting
# ---------------------------------------------------------------------------
def _ftable(d: dict) -> str:
    parts = []
    for k, v in d.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, str):
            v = util.lua_quote(v)
        parts.append(f"{k} = {v}")
    return "{" + ", ".join(parts) + "}"


def _ftable_str(items: list[str]) -> str:
    return "{" + ", ".join(util.lua_quote(i) for i in items) + "}"


def _nodebox(boxes: list) -> str:
    inner = []
    for b in boxes:
        inner.append("{" + ", ".join(
            _num(b[k]) for k in ("x1", "y1", "z1", "x2", "y2", "z2")
        ) + "}")
    return '{type = "fixed", fixed = {' + ", ".join(inner) + "}}"


def _num(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "0"
    if f == int(f):
        return str(int(f))
    return repr(round(f, 4))


def _lua_value(v) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"[{util.lua_quote(str(k))}] = {_lua_value(val)}"
                               if not _is_ident(k) else f"{k} = {_lua_value(val)}"
                               for k, val in v.items()) + "}"
    if isinstance(v, (list, tuple)):
        return "{" + ", ".join(_lua_value(x) for x in v) + "}"
    if isinstance(v, str):
        # preserve numeric counts separated by space
        return util.lua_quote(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "nil"
    return str(v)


def _is_ident(k) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)))


def _tr_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")


def _tool_kind(ident: str) -> tuple[str, str]:
    m = re.match(r"(?:.*_)?(wooden|stone|iron|golden|gold|diamond|netherite|copper|brass|steel|zinc|bronze)?_?(sword|pickaxe|axe|shovel|hoe|helmet|chestplate|leggings|boots)$", ident)
    if m:
        mat = m.group(1) or "iron"
        if mat == "golden":
            mat = "gold"
        return mat, m.group(2)
    # fallback: try to find any known material token
    for mat in _TOOL_MATERIALS:
        if mat in ident:
            for t in ("sword", "pickaxe", "axe", "shovel", "hoe"):
                if ident.endswith(t):
                    return mat, t
    return "iron", "pickaxe"
