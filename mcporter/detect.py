"""
Mod identification.

Reads the metadata file(s) shipped by every major loader and produces a
normalised ModInfo.  Supports compiled jars and source trees.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore

from . import util
from .jarfs import VirtualFS


@dataclass
class ModInfo:
    loader: str = "unknown"
    modid: str = "unknown"
    name: str = "Unknown Mod"
    version: str = "0.0.0"
    description: str = ""
    authors: list[str] = field(default_factory=list)
    license: str = ""
    mc_versions: list[str] = field(default_factory=list)
    depends: dict[str, str] = field(default_factory=dict)
    entrypoints: list[str] = field(default_factory=list)
    mixins: list[str] = field(default_factory=list)
    metadata_source: str = ""
    is_source: bool = False
    resource_root: str = ""       # prefix before assets/ and data/
    gradle_props: dict = field(default_factory=dict)
    datapack_namespaces: list = field(default_factory=list)
    datapack_file_counts: dict = field(default_factory=dict)

    @property
    def namespace(self) -> str:
        return self.modid


def _mc_versions_from_range(spec: str) -> list[str]:
    return re.findall(r"\d+\.\d+(?:\.\d+)?", spec or "")


def detect(fs: VirtualFS) -> ModInfo:
    info = ModInfo()
    info.gradle_props = _load_gradle_props(fs)

    # Source tree? Then the real metadata lives under src/*/resources.
    candidates = _resource_roots(fs)
    if candidates:
        info.is_source = True

    # --- Fabric ----------------------------------------------------------
    for root in candidates:
        p = f"{root}fabric.mod.json"
        if fs.exists(p):
            _parse_fabric(fs, p, root, info)
            return _finish(fs, info)

    # --- Quilt -----------------------------------------------------------
    for root in candidates:
        p = f"{root}quilt.mod.json"
        if fs.exists(p):
            _parse_quilt(fs, p, root, info)
            return _finish(fs, info)

    # --- NeoForge --------------------------------------------------------
    neoforge_hits = []
    for root in candidates:
        for name in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
            p = f"{root}{name}"
            if fs.exists(p):
                neoforge_hits.append((root, p, name))
    # prefer real resources over src/main/templates
    neoforge_hits.sort(key=lambda t: (1 if "templates" in t[1] else 0))
    if neoforge_hits:
        root, p, name = neoforge_hits[0]
        _parse_toml(fs, p, root, info, "neoforge" if "neoforge" in name else "forge")
        return _finish(fs, info)

    # --- Legacy Forge (1.12-) -------------------------------------------
    for root in candidates:
        p = f"{root}mcmod.info"
        if fs.exists(p):
            _parse_mcmod(fs, p, root, info)
            return _finish(fs, info)

    # --- LiteLoader (legacy, .litemod) -----------------------------------
    for p in fs.glob("", "litemod.json") + (["litemod.json"] if fs.exists("litemod.json") else []):
        if fs.exists(p):
            _parse_litemod(fs, p, info)
            return _finish(fs, info)

    # --- Bedrock behavior/resource packs (.mcpack/.mcaddon) --------------
    for p in fs.glob("", "manifest.json"):
        _parse_bedrock(fs, p, info)
        return _finish(fs, info)

    # --- Datapack / resource pack (worldgen / assets only) ---------------
    if fs.exists("pack.mcmeta") or any(p.endswith("pack.mcmeta") for p in fs.all_paths()):
        _parse_datapack(fs, info)
        return _finish(fs, info)

    # --- Fallback: fabric.mod.json anywhere ------------------------------
    hits = fs.glob("", "fabric.mod.json")
    if hits:
        root = hits[0][: -len("fabric.mod.json")]
        _parse_fabric(fs, hits[0], root, info)
        return _finish(fs, info)

    # --- Fallback: manifest + assets namespace ---------------------------
    _fallback_identify(fs, info)
    return _finish(fs, info)


def _finish(fs: VirtualFS, info: ModInfo) -> ModInfo:
    info.resource_root = find_resource_root(fs, info.namespace)
    return info


def find_resource_root(fs: VirtualFS, namespace: str) -> str:
    """Locate the prefix immediately before `assets/<ns>/` (or `data/<ns>/`)."""
    want = f"assets/{namespace}/"
    for p in fs.all_paths():
        idx = p.find(want)
        if idx >= 0:
            return p[:idx]
    want = f"data/{namespace}/"
    for p in fs.all_paths():
        idx = p.find(want)
        if idx >= 0:
            return p[:idx]
    return ""


def _load_gradle_props(fs: VirtualFS) -> dict:
    for p in fs.all_paths():
        if p.endswith("gradle.properties"):
            text = fs.text(p) or ""
            props = {}
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
            return props
    return {}


def _expand(text: str, props: dict) -> str:
    def repl(m):
        return props.get(m.group(1), m.group(0))
    return re.sub(r"\$\{([a-zA-Z0-9_.]+)\}", repl, text)


def _resource_roots(fs: VirtualFS) -> list[str]:
    """Return candidate resource roots (with trailing slash) in a source tree."""
    roots = [""]
    for p in fs.all_paths():
        if p.endswith("fabric.mod.json") or p.endswith("quilt.mod.json"):
            r = p[: -len("fabric.mod.json")]
            if r not in roots:
                roots.append(r)
        if p.endswith("mods.toml") or p.endswith("mods.toml".replace("mods", "neoforge.mods")):
            r = p[: p.rfind("META-INF/")]
            if r not in roots:
                roots.append(r)
    # ensure main resources root is tried first for source trees
    for p in fs.all_paths():
        if "src/main/resources/" in p:
            r = p[: p.index("src/main/resources/")] + "src/main/resources/"
            if r not in roots:
                roots.insert(1, r)
            break
    return roots


def _parse_fabric(fs: VirtualFS, path: str, root: str, info: ModInfo) -> None:
    data = util.load_json(fs.read(path) or b"{}")
    info.loader = "fabric"
    info.metadata_source = path
    info.modid = _expand(str(data.get("id", info.modid)), info.gradle_props)
    info.name = _expand(str(data.get("name", info.modid)), info.gradle_props)
    info.version = _expand(str(data.get("version", info.version)), info.gradle_props)
    info.description = _expand(data.get("description", ""), info.gradle_props)
    if isinstance(info.description, dict):
        info.description = ""
    info.authors = _authors(data.get("authors"))
    info.license = data.get("license", "") if isinstance(data.get("license"), str) else ""
    info.mc_versions = _mc_versions_from_range(data.get("depends", {}).get("minecraft", ""))
    for k, v in (data.get("depends") or {}).items():
        info.depends[k] = str(v)
    for ep_type, eps in (data.get("entrypoints") or {}).items():
        for ep in eps:
            if isinstance(ep, str):
                info.entrypoints.append(f"{ep_type}:{ep}")
            elif isinstance(ep, dict) and "value" in ep:
                info.entrypoints.append(f"{ep_type}:{ep['value']}")
    for m in (data.get("mixins") or []):
        info.mixins.append(m if isinstance(m, str) else m.get("config", str(m)))


def _parse_quilt(fs: VirtualFS, path: str, root: str, info: ModInfo) -> None:
    data = util.load_json(fs.read(path) or b"{}")
    info.loader = "quilt"
    info.metadata_source = path
    ql = data.get("quilt_loader", {})
    info.modid = ql.get("id", info.modid)
    info.version = str(ql.get("version", info.version))
    meta = ql.get("metadata", {})
    info.name = meta.get("name", info.modid)
    info.description = meta.get("description", "")
    info.authors = _authors(meta.get("contributors"))
    info.depends = {k: str(v) for k, v in (ql.get("depends") or {}).items()}
    info.mc_versions = _mc_versions_from_range(info.depends.get("minecraft", ""))


def _parse_toml(fs: VirtualFS, path: str, root: str, info: ModInfo, loader: str) -> None:
    info.loader = loader
    info.metadata_source = path
    text = fs.text(path) or ""
    text = _expand(text, info.gradle_props)
    mf_ver = _manifest_version(fs)
    if mf_ver:
        text = text.replace("${file.jarVersion}", mf_ver)
    data = {}
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception:
            data = {}
    if not data:
        data = _mini_toml(text)
    mods = data.get("mods") or []
    if mods:
        m = mods[0]
        info.modid = m.get("modId", info.modid)
        info.name = m.get("displayName", info.modid)
        info.version = str(m.get("version", info.version))
        info.description = m.get("description", "")
        info.authors = _authors(m.get("authors")) or _authors(m.get("author"))
        info.license = m.get("license", "")
    deps = {}
    dep_root = data.get("dependencies") or {}
    dep_dicts = []
    if isinstance(dep_root, list):
        dep_dicts = [d for d in dep_root if isinstance(d, dict)]
    elif isinstance(dep_root, dict):
        for v in dep_root.values():
            if isinstance(v, list):
                dep_dicts.extend(d for d in v if isinstance(d, dict))
            elif isinstance(v, dict):
                dep_dicts.append(v)
    for d in dep_dicts:
        did = d.get("modId", "")
        if did:
            deps[did] = str(d.get("versionRange", ""))
    info.depends = deps
    info.mc_versions = _mc_versions_from_range(deps.get("minecraft", ""))
    info.mixins = re.findall(r'config\s*=\s*"([^"]+)"', text)
    # description may be a multiline literal in the TOML
    m = re.search(r'description\s*=\s*"""(.*?)"""', text, re.S)
    if m:
        info.description = m.group(1).strip()


def _parse_datapack(fs: VirtualFS, info: ModInfo) -> None:
    info.loader = "datapack"
    mcmeta = None
    for p in fs.all_paths():
        if p.endswith("pack.mcmeta"):
            mcmeta = p
            break
    info.metadata_source = mcmeta or "pack.mcmeta"
    if mcmeta:
        try:
            data = util.load_json(fs.read(mcmeta) or b"{}")
        except Exception:
            data = {}
        pack = data.get("pack", {})
        pid = pack.get("id")
        if isinstance(pid, str) and pid:
            info.modid = pid
            info.name = util.titleize(pid)
        desc = pack.get("description")
        if isinstance(desc, list):
            info.description = "".join(
                d.get("text", "") for d in desc if isinstance(d, dict))
        elif isinstance(desc, str):
            info.description = desc
        info.version = str(pack.get("pack_format", info.version))
    # distinguish a pure resource pack from a data pack
    has_data = any(p.startswith("data/") or "/data/" in p for p in fs.all_paths())
    has_assets = any(p.startswith("assets/") or "/assets/" in p for p in fs.all_paths())
    if has_assets and not has_data:
        info.loader = "resourcepack"
    # dominant data namespace (excluding vanilla/loader namespaces)
    counts: dict[str, int] = {}
    for p in fs.all_paths():
        parts = p.split("/")
        if "data" in parts:
            di = parts.index("data")
            if di + 1 < len(parts) and parts[di + 1]:
                counts[parts[di + 1]] = counts.get(parts[di + 1], 0) + 1
    for ns in ("minecraft", "c", "forge", "neoforge", "fabric", ""):
        counts.pop(ns, None)
    if counts and info.modid in ("unknown",):
        info.modid = max(counts, key=counts.get)
        info.name = util.titleize(info.modid)
    info.datapack_namespaces = sorted(counts, key=counts.get, reverse=True)
    info.datapack_file_counts = counts


def _parse_mcmod(fs: VirtualFS, path: str, root: str, info: ModInfo) -> None:
    data = util.load_json(fs.read(path) or b"[]")
    info.loader = "forge-legacy"
    info.metadata_source = path
    if isinstance(data, list) and data:
        m = data[0]
    elif isinstance(data, dict):
        m = (data.get("modList") or [data])[0]
    else:
        m = {}
    info.modid = m.get("modid", info.modid)
    info.name = m.get("name", info.modid)
    info.version = str(m.get("version", info.version))
    info.description = m.get("description", "")
    info.authors = _authors(m.get("authorList")) or _authors(m.get("authors"))
    info.mc_versions = _mc_versions_from_range(m.get("mcversion", ""))
    info.depends = {d: "*" for d in (m.get("dependencies") or [])}


def _manifest_version(fs: VirtualFS) -> str:
    mf = fs.text("META-INF/MANIFEST.MF") or ""
    m = re.search(r"(?im)^Implementation-Version:\s*(.+)$", mf)
    return m.group(1).strip() if m else ""


def _parse_litemod(fs: VirtualFS, path: str, info: ModInfo) -> None:
    """LiteLoader `.litemod` metadata (legacy)."""
    data = util.load_json(fs.read(path) or b"{}")
    info.loader = "litemod"
    info.metadata_source = path
    info.modid = str(data.get("name", info.modid))
    info.name = str(data.get("name", info.modid))
    info.version = str(data.get("version", info.version))
    info.authors = _authors(data.get("author"))
    info.mc_versions = _mc_versions_from_range(data.get("mcversion", ""))
    info.description = data.get("description", "")


def _parse_bedrock(fs: VirtualFS, path: str, info: ModInfo) -> None:
    """Bedrock Edition behavior/resource packs (manifest.json)."""
    data = util.load_json(fs.read(path) or b"{}")
    info.loader = "bedrock"
    info.metadata_source = path
    header = data.get("header", {}) if isinstance(data, dict) else {}
    name = header.get("name", "")
    info.modid = util.lua_name(name) if name else info.modid
    info.name = name or "Bedrock Pack"
    info.version = str(header.get("version", info.version))
    desc = header.get("description", "")
    info.description = desc if isinstance(desc, str) else ""
    modules = data.get("modules", []) if isinstance(data, dict) else []
    info.depends = {}
    for mod in modules:
        if isinstance(mod, dict) and mod.get("type"):
            info.entrypoints.append(f"bedrock:{mod.get('type')}")


def _fallback_identify(fs: VirtualFS, info: ModInfo) -> None:
    """Last resort: infer namespace from assets/, derive loader from class refs."""
    namespaces: list[str] = []
    for p in fs.all_paths():
        if p.startswith("assets/") and p.count("/") >= 1:
            ns = p.split("/")[1]
            if ns not in ("minecraft", "realms") and ns not in namespaces:
                namespaces.append(ns)
    if namespaces:
        info.modid = namespaces[0]
        info.name = util.titleize(info.modid)
    refs = " ".join(fs.glob("", ".class")[:50])
    if any("fabric" in p.lower() for p in fs.all_paths()[:2000]):
        info.loader = "fabric?"
    elif fs.exists("META-INF/mods.toml"):
        info.loader = "forge?"
    # search manifest
    mf = fs.text("META-INF/MANIFEST.MF")
    if mf:
        mm = re.search(r"(?im)^Implementation-Title:\s*(.+)$", mf)
        if mm and info.name == "Unknown Mod":
            info.name = mm.group(1).strip()
        mv = re.search(r"(?im)^Implementation-Version:\s*(.+)$", mf)
        if mv:
            info.version = mv.group(1).strip()
    info.metadata_source = "fallback"


def _authors(value) -> list[str]:
    out: list[str] = []

    def add(v):
        if isinstance(v, str):
            if v:
                out.append(v)
        elif isinstance(v, list):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            if "name" in v:
                add(v.get("name"))
            else:
                for x in v.values():
                    add(x)

    add(value)
    # de-duplicate, keep order
    seen = set()
    return [a for a in out if not (a in seen or seen.add(a))]


def _mini_toml(text: str) -> dict:
    """Extremely small TOML subset parser (fallback when tomllib missing)."""
    data: dict = {}
    cur = data
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[[") and line.endswith("]]"):
            key = line[2:-2].strip()
            data.setdefault(key, []).append({})
            cur = data[key][-1]
        elif line.startswith("[") and line.endswith("]"):
            key = line[1:-1].strip()
            data.setdefault(key, {})
            cur = data[key]
        elif "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            cur[k.strip()] = v
    return data
