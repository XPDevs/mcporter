#!/usr/bin/env python3
"""
mcporter command line interface.

    python3 port.py <mod.jar | mod_dir | source_dir> [more inputs...] \
        [-o OUT] [--game auto|voxelibre|mtg] [--install]

Translates any Minecraft mod (Fabric / Quilt / Forge / NeoForge / legacy /
LiteLoader / datapack / resource pack / Bedrock pack, as a compiled jar or a
source tree) into a Luanti mod, entirely in pure Python (standard library
only).

By default the finished mod is written to a folder named after the mod, and
the target game is auto-detected from the Luanti games installed on this
machine.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

from mcporter import __version__, util
from mcporter.assets import AssetIndex, VanillaAssets
from mcporter.detect import detect
from mcporter.emit import Emitter
from mcporter import games as games_mod
from mcporter.jarfs import VirtualFS
from mcporter.loot import build_loot_map
from mcporter.recipes import IdMapper, RecipeTranslator, TagIndex
from mcporter.registry import RegistryBuilder
from mcporter import report as report_mod
from mcporter import luacheck

# loaders that only carry assets / data and have no Java bytecode to translate
_DATA_ONLY = {"datapack", "resourcepack", "bedrock"}


def find_default_vanilla() -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.join(os.getcwd(), "minecraft", "client.jar"),
        os.path.join(here, "minecraft", "client.jar"),
        os.path.join(os.path.dirname(here), "minecraft", "client.jar"),
    ):
        if os.path.exists(cand):
            return cand
    env = os.environ.get("MC_CLIENT_JAR")
    if env and os.path.exists(env):
        return env
    return None


def safe_folder_name(name: str, fallback: str) -> str:
    """Turn a mod's display name into a filesystem-safe folder name."""
    out = []
    for ch in name or "":
        out.append(ch if (ch.isalnum() or ch in "._-") else "_")
    cleaned = "".join(out).strip("._")
    if not cleaned or cleaned.lower() in ("unknown_mod", "unknown"):
        cleaned = util.lua_name(fallback)
    return cleaned


def gather_logic(fs: VirtualFS, max_classes: int = 6000):
    """Translate every compiled .class file into a Lua reference module."""
    from mcporter.j2l import J2LStats, translate_classes
    paths = fs.glob("", ".class")
    if not paths:
        return {}, None
    # skip obvious library/shaded noise directories
    def keep(p: str) -> bool:
        low = p.lower()
        return not any(seg in low for seg in ("/shadow/", "/shaded/"))
    paths = [p for p in paths if keep(p)][:max_classes]
    data = []
    for p in paths:
        b = fs.read(p)
        if b:
            data.append((p, b))
    stats = J2LStats()
    files = translate_classes(data, stats)
    return files, stats


def port(input_path: str, outdir: str | None = None, game: str = "voxelibre",
         vanilla_path: str | None = None, quiet: bool = False,
         no_logic: bool = False, install: bool = False,
         mods_dir: str | None = None) -> dict:
    t0 = time.time()
    log = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))

    log(f"[mcporter] opening {input_path}")
    fs = VirtualFS(input_path)
    info = detect(fs)
    log(f"[mcporter] identified: {info.name} (id={info.modid}, loader={info.loader}, "
        f"version={info.version})")

    if vanilla_path is None:
        vanilla_path = find_default_vanilla()
    vanilla = VanillaAssets(vanilla_path)
    if vanilla.fs is not None:
        log(f"[mcporter] using vanilla assets: {vanilla_path}")

    log("[mcporter] indexing assets ...")
    assets = AssetIndex(fs, info.namespace, vanilla, info.resource_root)

    log("[mcporter] reading tags ...")
    tags = TagIndex(fs, info.namespace, vanilla, info.resource_root)

    log("[mcporter] discovering blocks/items (assets + bytecode) ...")
    builder = RegistryBuilder(fs, assets, info.namespace)
    entries = builder.build()
    log(f"[mcporter] discovered {len(entries)} content entries "
        f"({builder.stats()['kinds']})")

    known = {f"{info.namespace}:{e}" for e in entries}
    mapper = IdMapper(info.namespace, game, known, tags)

    log("[mcporter] translating recipes ...")
    translator = RecipeTranslator(fs, info.namespace, mapper, vanilla, info.resource_root)
    recipes = translator.translate_all()
    log(f"[mcporter] translated {len(recipes)} recipes")

    loot = build_loot_map(fs, info.namespace, mapper, info.resource_root)

    logic: dict = {}
    j2l_stats = None
    if not no_logic and info.loader not in _DATA_ONLY:
        log("[mcporter] translating Java bytecode -> Lua ...")
        logic, j2l_stats = gather_logic(fs)
        if j2l_stats is not None:
            log(f"[mcporter] java->lua: {j2l_stats.translated_methods}/"
                f"{j2l_stats.methods} methods from {j2l_stats.classes} classes")

    if outdir is None:
        folder = safe_folder_name(info.name, info.namespace)
        outdir = os.path.join(os.getcwd(), folder)
    log(f"[mcporter] emitting Luanti mod -> {outdir}")
    emitter = Emitter(outdir, info, entries, recipes, loot, assets, game, vanilla,
                      logic, j2l_stats)
    emit_stats = emitter.emit()

    all_notes = list(emitter.notes)
    if vanilla.fs is None:
        all_notes.append("vanilla client.jar not found: vanilla textures used by "
                         "recipes/models could not be copied and were replaced with placeholders")
    if logic:
        all_notes.append("the logic/ folder is a best-effort Java->Lua *reference* "
                         "translation; it is loaded defensively (pcall) and does not "
                         "replace the manual work listed below")

    worldgen = report_mod.scan_worldgen(fs, info.namespace, info.resource_root)
    if info.loader == "datapack":
        all_notes.append("source is a datapack: only worldgen/structure/loot data is present; "
                         "there is no code or asset content to translate")
    elif info.loader == "resourcepack":
        all_notes.append("source is a resource pack: it only ships textures/models/lang")
    elif info.loader == "bedrock":
        all_notes.append("source is a Bedrock Edition pack: Bedrock formats are not "
                         "translated (Java Edition only)")

    lua_issues = luacheck.check_mod(outdir)
    if lua_issues:
        all_notes.append(f"Lua syntax check found issues in {len(lua_issues)} file(s)")
    else:
        all_notes.append("Lua syntax check passed (balanced blocks/brackets)")

    report = report_mod.build_report(
        info, entries, recipes, builder.java_features, emit_stats,
        all_notes, builder.mixin_files, worldgen,
    )
    report["lua_check"] = lua_issues
    report["output"] = outdir
    report["game"] = game
    report["elapsed_seconds"] = round(time.time() - t0, 2)
    if j2l_stats is not None:
        report["java_to_lua"] = {
            "classes": j2l_stats.classes,
            "methods": j2l_stats.methods,
            "translated_methods": j2l_stats.translated_methods,
            "instructions": j2l_stats.instructions,
            "untranslated_opcodes": dict(sorted(
                j2l_stats.unsupported.items(), key=lambda x: -x[1])),
        }

    report_mod.write_markdown(report, outdir, info)
    report_mod.write_json(report, outdir)

    if install and mods_dir:
        dest = os.path.join(mods_dir, os.path.basename(outdir.rstrip("/")))
        try:
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            shutil.copytree(outdir, dest)
            log(f"[mcporter] installed into {dest}")
            report["installed_to"] = dest
        except OSError as exc:
            log(f"[mcporter] install failed: {exc}")

    log(f"[mcporter] done in {report['elapsed_seconds']}s  -> "
        f"score {report['translation_score']}%  report: {outdir}/TRANSLATION_REPORT.md")
    return report


# ---------------------------------------------------------------------------
# input expansion (single mod, or a folder full of mods)
# ---------------------------------------------------------------------------
_MOD_MARKERS = (
    "fabric.mod.json", "quilt.mod.json", "mcmod.info", "litemod.json",
    "manifest.json",
)
_MOD_MARKER_DIRS = ("assets", "data", "META-INF", "src", "mods")


def looks_like_mod(path: str) -> bool:
    if os.path.isfile(path):
        return True
    try:
        names = set(os.listdir(path))
    except OSError:
        return False
    if any(m in names for m in _MOD_MARKERS):
        return True
    if any(d in names for d in _MOD_MARKER_DIRS):
        return True
    return False


def expand_inputs(inputs: list[str]) -> tuple[list[str], bool]:
    """Return (mod_paths, was_batch).

    A directory that is itself a mod is kept; a directory that merely contains
    many mods is expanded into the mod files it holds.
    """
    out: list[str] = []
    batch = len(inputs) > 1
    for p in inputs:
        if os.path.isdir(p) and not looks_like_mod(p):
            found = []
            for base, _dirs, files in os.walk(p):
                if base.count(os.sep) - p.rstrip(os.sep).count(os.sep) > 3:
                    continue
                for f in files:
                    if f.lower().endswith((".jar", ".zip", ".mcpack", ".mcaddon", ".litemod")):
                        found.append(os.path.join(base, f))
            if found:
                batch = True
                out.extend(sorted(found))
                continue
        out.append(p)
    return out, batch


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="mcporter",
        description="Translate any Minecraft mod into a Luanti mod (pure Python).",
    )
    ap.add_argument("input", nargs="*",
                    help="mod .jar/.zip, extracted dir, source tree, or a folder of mods")
    ap.add_argument("-o", "--out", default=None,
                    help="output directory (default: a folder named after the mod)")
    ap.add_argument("--game", default="auto", choices=["auto", "voxelibre", "mtg"],
                    help="target Luanti game profile (default: auto-detect installed games)")
    ap.add_argument("--game-path", default=None,
                    help="extra directory to search for installed Luanti games")
    ap.add_argument("--vanilla", default=None,
                    help="path to a Minecraft client.jar for vanilla assets")
    ap.add_argument("--no-logic", action="store_true",
                    help="skip the Java bytecode -> Lua translation pass")
    ap.add_argument("--install", action="store_true",
                    help="copy the finished mod into the detected Luanti mods/ directory")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="non-interactive: never prompt, use auto-detected defaults")
    ap.add_argument("--json", action="store_true", help="print the JSON report(s) to stdout")
    ap.add_argument("--quiet", action="store_true", help="suppress progress output")
    ap.add_argument("--version", action="version", version=f"mcporter {__version__}")
    args = ap.parse_args(argv)

    interactive = not args.yes

    if not args.input:
        if interactive and sys.stdin.isatty():
            try:
                entered = input(
                    "Enter the path to a Minecraft mod (.jar, .zip, .litemod, "
                    "or a folder): ").strip().strip('"').strip("'")
            except (EOFError, KeyboardInterrupt):
                entered = ""
            if entered:
                args.input = [entered]
        if not args.input:
            ap.print_help()
            return 2

    for p in args.input:
        if not os.path.exists(p):
            print(f"error: input not found: {p}", file=sys.stderr)
            return 2

    # resolve the target game once
    game = args.game
    if game == "auto":
        installed = games_mod.scan_games(args.game_path)
        if installed:
            if not args.quiet:
                for g in installed:
                    label = games_mod.PROFILES.get(g.profile, ("?",))[0] \
                        if g.profile else "unknown"
                    print(f"[mcporter] found game: {g.title} [{g.game_id}] -> {label}",
                          flush=True)
        elif not args.quiet:
            print("[mcporter] no Luanti game installation detected "
                  "(set --game mtg/voxelibre or --game-path to override; "
                  "defaulting to voxelibre)", flush=True)
        game = games_mod.choose_game(installed, interactive)
        if not args.quiet:
            print(f"[mcporter] targeting game profile: {game}", flush=True)

    mods_dir = games_mod.mods_dir_for_user_path() if args.install else None
    if args.install and not mods_dir:
        print("error: could not locate a Luanti mods/ directory for --install",
              file=sys.stderr)
        return 2

    inputs, batch = expand_inputs(args.input)
    if batch and not args.quiet:
        print(f"[mcporter] batch mode: {len(inputs)} mod(s) to translate", flush=True)

    reports = []
    exit_code = 0
    for p in inputs:
        try:
            rep = port(p, args.out, game, args.vanilla, args.quiet,
                       args.no_logic, args.install, mods_dir)
            reports.append(rep)
        except Exception as exc:  # noqa: BLE001
            if os.environ.get("MCPORTER_DEBUG"):
                raise
            print(f"error: {p}: {exc}", file=sys.stderr)
            exit_code = 1

    if args.json:
        import json
        payload = reports[0] if len(reports) == 1 else reports
        print(json.dumps(payload, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
