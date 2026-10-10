"""Translation report generation (markdown + machine-readable JSON)."""

from __future__ import annotations

import json
import os
from typing import Optional

from . import util
from .detect import ModInfo
from .registry import Entry
from .recipes import TranslatedRecipe

# Java systems that static translation cannot reproduce.
UNSUPPORTED = {
    "entity": "Custom entities / mobs (AI, pathfinding, rendering)",
    "block_entity": "Block entities with runtime state (tile entities)",
    "gui": "Custom GUIs / screens",
    "client_render": "Custom client-side rendering / models / shaders",
    "networking": "Client<->server networking / packets",
    "fluid": "Custom fluids (fluid simulation & rendering)",
    "capability": "Capabilities / energy / item-handler logic",
    "container_menu": "Container menus / inventory slots",
    "codec": "Data (de)serialisation codecs",
    "mixin": "Mixins (bytecode patches into Minecraft)",
    "extends_Mob": "Mob subclasses",
    "extends_LivingEntity": "Living-entity subclasses",
    "extends_Entity": "Entity subclasses",
    "extends_BlockEntity": "Block-entity subclasses",
    "extends_Fluid": "Fluid subclasses",
    "extends_Menu": "Container-menu subclasses",
    "extends_CreativeModeTab": "Custom creative tabs",
    "extends_Enchantment": "Custom enchantments",
    "extends_Potion": "Custom potions",
    "extends_Effect": "Custom status effects",
}


def build_report(info: ModInfo, entries: dict[str, Entry], recipes: list[TranslatedRecipe],
                 features: dict[str, int], emit_stats: dict, notes: list[str],
                 mixin_files: list[str], worldgen: Optional[dict] = None) -> dict:
    kinds: dict[str, int] = {}
    for e in entries.values():
        kinds[e.kind] = kinds.get(e.kind, 0) + 1

    supported_features = {"extends_Block", "extends_Item", "extends_BlockItem",
                          "extends_SwordItem", "extends_PickaxeItem", "extends_AxeItem",
                          "extends_ShovelItem", "extends_HoeItem", "extends_ArmorItem"}
    blockers = {k: v for k, v in features.items() if k in UNSUPPORTED}

    content_total = len(entries)
    content_high = sum(1 for e in entries.values() if e.confidence >= 0.6)
    content_med = sum(1 for e in entries.values() if 0.35 <= e.confidence < 0.6)
    content_low = sum(1 for e in entries.values() if e.confidence < 0.35)

    covered_units = content_total + len(recipes)
    blocking_units = sum(blockers.values())
    if covered_units + blocking_units > 0:
        score = round(100.0 * covered_units / (covered_units + blocking_units), 1)
    else:
        score = 0.0

    return {
        "identity": {
            "loader": info.loader,
            "modid": info.modid,
            "name": info.name,
            "version": info.version,
            "authors": info.authors,
            "license": info.license,
            "mc_versions": info.mc_versions,
            "depends": info.depends,
            "metadata_source": info.metadata_source,
            "resource_root": info.resource_root,
        },
        "content": {
            "total": content_total,
            "kinds": kinds,
            "high_confidence": content_high,
            "medium_confidence": content_med,
            "low_confidence": content_low,
            "recipes_translated": len(recipes),
            "textures_written": emit_stats.get("textures_written", 0),
            "missing_textures": emit_stats.get("missing_textures", []),
            "logic_files": emit_stats.get("logic_files", 0),
        },
        "worldgen": worldgen or {},
        "data_namespaces": info.datapack_namespaces,
        "java_features": features,
        "unsupported": {k: {"count": v, "reason": UNSUPPORTED[k]} for k, v in blockers.items()},
        "mixins": mixin_files,
        "translation_score": score,
        "notes": notes,
    }


def scan_worldgen(fs, namespace: str, resource_root: str = "") -> dict:
    """Count data-driven worldgen / datapack content that has no Luanti equivalent."""
    wg: dict[str, int] = {}
    structures: list[str] = []
    for p in fs.all_paths():
        parts = p.split("/")
        if "data" not in parts:
            continue
        di = parts.index("data")
        if di + 1 >= len(parts) or parts[di + 1] != namespace:
            continue
        rest = parts[di + 2:]
        key = None
        if "worldgen" in rest:
            wi = rest.index("worldgen")
            if wi + 1 < len(rest):
                key = "worldgen/" + rest[wi + 1]
        elif rest and rest[0] in ("structures", "structure"):
            key = "structures"
            if p.endswith(".nbt"):
                structures.append(p)
        elif rest and rest[0] in ("loot_table", "loot_tables"):
            key = "loot_tables"
        elif rest and rest[0] in ("advancement", "advancements"):
            key = "advancements"
        elif rest and rest[0] in ("tags",):
            key = "tags"
        elif rest and rest[0] in ("functions", "tags/functions"):
            key = "functions"
        if key:
            wg[key] = wg.get(key, 0) + 1
    out = {"counts": dict(sorted(wg.items(), key=lambda x: -x[1]))}
    if structures:
        out["structures"] = len(structures)
        out["structure_examples"] = structures[:5]
    return out


def write_markdown(report: dict, outdir: str, info: ModInfo) -> str:
    idn = report["identity"]
    c = report["content"]
    lines = [
        f"# Translation Report: {idn['name']}",
        "",
        f"Ported by **mcporter** from Minecraft (`{idn['loader']}`) to Luanti.",
        "",
        "## Identification",
        "",
        f"- Loader: `{idn['loader']}`",
        f"- Mod id: `{idn['modid']}`",
        f"- Version: `{idn['version']}`",
        f"- Authors: {', '.join(idn['authors']) or 'n/a'}",
        f"- License: `{idn['license'] or 'unknown'}`",
        f"- Minecraft versions: {', '.join(idn['mc_versions']) or 'n/a'}",
        f"- Metadata source: `{idn['metadata_source']}`",
        "",
        "## Automatic coverage",
        "",
        f"- **Translation score: {report['translation_score']}%** "
        f"(content units successfully translated vs. Java systems that cannot be)",
        f"- Blocks/items discovered: **{c['total']}**",
        f"  - high confidence: {c['high_confidence']}",
        f"  - medium confidence: {c['medium_confidence']}",
        f"  - low confidence: {c['low_confidence']}",
        f"- Breakdown: {', '.join(f'{k}={v}' for k, v in c['kinds'].items()) or 'none'}",
        f"- Recipes translated: **{c['recipes_translated']}**",
        f"- Textures written: **{c['textures_written']}**",
        f"- Missing textures (placeholders used): **{len(c['missing_textures'])}**",
        "",
    ]

    j2l = report.get("java_to_lua")
    if j2l:
        lines += [
            "## Java -> Lua translation",
            "",
            f"- Classes translated: **{j2l['classes']}**",
            f"- Methods translated: **{j2l['translated_methods']}** / {j2l['methods']}",
            f"- Files written to `logic/`: **{c.get('logic_files', 0)}**",
            "",
            "This is a **best-effort reference translation** of the compiled JVM",
            "bytecode. It recovers constants, fields, method calls, arithmetic,",
            "array access and returns; control flow is emitted as annotated",
            "`-- if ... then goto @offset` comments (Luanti's Lua has no `goto`).",
            "It is loaded defensively and is meant as a map for a human porter,",
            "not as a drop-in runtime implementation.",
            "",
        ]
        if j2l.get("untranslated_opcodes"):
            lines.append("| untranslated opcode | occurrences |")
            lines.append("| --- | --- |")
            for k, v in j2l["untranslated_opcodes"].items():
                lines.append(f"| `{k}` | {v} |")
            lines.append("")
    elif c.get("logic_files"):
        lines += ["## Java -> Lua translation", "",
                  f"- Files written to `logic/`: **{c['logic_files']}**", ""]
    else:
        lines += [
            "## Java -> Lua translation",
            "",
            "_No compiled `.class` files were found (for example this is a source"
            " tree or a data-only pack), so no bytecode translation was produced._",
            "",
        ]

    lines += [
        "## Java systems detected that need manual work",
        "",
    ]
    if report["unsupported"]:
        lines.append("| system | occurrences | why it can't be auto-ported |")
        lines.append("| --- | --- | --- |")
        for k, v in sorted(report["unsupported"].items(), key=lambda x: -x[1]["count"]):
            lines.append(f"| `{k}` | {v['count']} | {v['reason']} |")
    else:
        lines.append("_None detected - this mod is purely data/asset driven._")
    lines.append("")

    if report.get("worldgen", {}).get("counts"):
        lines += ["## Data-driven / worldgen content detected", ""]
        lines.append("| category | files | portability |")
        lines.append("| --- | --- | --- |")
        wg = report["worldgen"]["counts"]
        for k, v in wg.items():
            portability = "not portable (needs re-authoring)" if k.startswith("worldgen") else \
                ("approximated via crafting" if k.startswith("loot") else "report only")
            lines.append(f"| `{k}` | {v} | {portability} |")
        if report["worldgen"].get("structures"):
            lines.append("")
            lines.append(f"Structure `.nbt` files found: **{report['worldgen']['structures']}** "
                         "(require NBT->schematic conversion, not automatic).")
        lines.append("")

    if report["mixins"]:
        lines += ["## Mixin configs (manual)", ""]
        for m in report["mixins"]:
            lines.append(f"- `{m}`")
        lines += ["", "Mixins patch Minecraft internals directly and have no Luanti equivalent.", ""]

    models = sorted(
        ((e.ident, e.confidence) for e in []), key=lambda x: x[1]
    )  # placeholder (kept simple)
    if report["notes"]:
        lines += ["## Notes", ""]
        for n in report["notes"]:
            lines.append(f"- {n}")
        lines.append("")

    lines += [
        "## How to install",
        "",
        f"1. Copy this folder into your Luanti `mods/` directory as `{util.lua_name(info.namespace)}`.",
        "2. Enable it in the world configuration.",
        "3. Provide the optional dependencies listed in `mod.conf` for full textures/sounds.",
        "",
    ]
    path = os.path.join(outdir, "TRANSLATION_REPORT.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def write_json(report: dict, outdir: str) -> str:
    path = os.path.join(outdir, ".mcporter_report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    return path
