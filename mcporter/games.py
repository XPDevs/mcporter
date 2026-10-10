"""
Luanti / Minetest installation discovery.

When the user does not pass `--game`, mcporter looks for Luanti games that are
actually installed on this machine and asks which one to target.  A game's
"profile" decides the item-id namespace and dependencies of the generated mod:

    voxelibre  -> mcl_* / VoxeLibre / MineClone(2|nia|5)   (Minecraft-like)
    mtg        -> default:* / Minetest Game                (vanilla Minetest)

Nothing is hardcoded about *mods* here; only the well-known base games are
recognised so the ported content integrates with what the user has installed.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

# profile -> (human name, mods that identify the game)
PROFILES = {
    "voxelibre": ("VoxeLibre / MineClone (Minecraft-like)", ("mcl_core",)),
    "mtg": ("Minetest Game (default)", ("default",)),
}


@dataclass
class InstalledGame:
    game_id: str
    title: str
    path: str
    profile: Optional[str]
    mods_seen: tuple


def user_paths() -> list[str]:
    """Return candidate Luanti user-data directories (most specific first)."""
    out: list[str] = []
    for env in ("LUANTI_USER_PATH", "MINETEST_USER_PATH", "MT_USER_PATH"):
        v = os.environ.get(env)
        if v:
            out.append(os.path.expanduser(v))
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            out += [os.path.join(appdata, "Luanti"), os.path.join(appdata, "Minetest")]
    elif sys.platform == "darwin":
        out += [os.path.join(home, "Library", "Application Support", "luanti"),
                os.path.join(home, "Library", "Application Support", "minetest")]
    else:
        out += [
            os.path.join(home, ".var", "app", "org.luanti.luanti", ".minetest"),  # flatpak
            os.path.join(home, ".minetest"),
            os.path.join(home, ".luanti"),
            os.path.join(home, "snap", "luanti", "current", ".minetest"),
        ]
    # de-duplicate, keep order
    seen = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def candidate_game_dirs(explicit: Optional[str] = None) -> list[str]:
    dirs: list[str] = []
    if explicit:
        dirs.append(os.path.expanduser(explicit))
    env = os.environ.get("LUANTI_GAME_PATH") or os.environ.get("MINETEST_GAME_PATH")
    if env:
        dirs.extend(p for p in env.split(os.pathsep) if p)
    for up in user_paths():
        dirs.append(os.path.join(up, "games"))
    seen = set()
    return [d for d in dirs if not (d in seen or seen.add(d)) and os.path.isdir(d)]


def _find_mod(name: str, game_dir: str, depth: int = 3) -> bool:
    want = name
    base_depth = game_dir.rstrip("/").count(os.sep)
    for root, dirs, _files in os.walk(game_dir):
        if root.count(os.sep) - base_depth > depth:
            dirs[:] = []
            continue
        for d in dirs:
            if d == want:
                return True
    return False


def identify_game(game_dir: str) -> InstalledGame:
    game_id = os.path.basename(game_dir.rstrip("/"))
    title = game_id
    conf = os.path.join(game_dir, "game.conf")
    if os.path.isfile(conf):
        try:
            with open(conf, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("title") and "=" in line:
                        title = line.split("=", 1)[1].strip().strip('"')
                        break
        except OSError:
            pass
    profile = None
    mods_seen: list[str] = []
    for prof, (_label, markers) in PROFILES.items():
        for marker in markers:
            if _find_mod(marker, game_dir):
                profile = prof
                mods_seen.append(marker)
                break
        if profile:
            break
    return InstalledGame(game_id, title, game_dir, profile, tuple(mods_seen))


def scan_games(explicit: Optional[str] = None) -> list[InstalledGame]:
    out: list[InstalledGame] = []
    seen: set[str] = set()
    for gdir in candidate_game_dirs(explicit):
        try:
            entries = sorted(os.listdir(gdir))
        except OSError:
            continue
        for name in entries:
            full = os.path.join(gdir, name)
            if not os.path.isdir(full):
                continue
            # a game dir must look like a game (game.conf, mods/, menu/)
            if not (os.path.isfile(os.path.join(full, "game.conf"))
                    or os.path.isdir(os.path.join(full, "mods"))):
                continue
            if os.path.realpath(full) in seen:
                continue
            seen.add(os.path.realpath(full))
            out.append(identify_game(full))
    return out


def mods_dir_for_user_path() -> Optional[str]:
    """Best guess at the user 'mods' directory (for --install)."""
    for up in user_paths():
        if os.path.isdir(up):
            return os.path.join(up, "mods")
    return None


def choose_game(games: list[InstalledGame], interactive: bool,
                default: str = "voxelibre") -> str:
    """Pick a target profile from the installed games.

    If exactly one known profile is installed it is selected automatically.
    Otherwise the user is prompted (when interactive) or the default is used.
    """
    known = [g for g in games if g.profile]
    profiles = []
    for g in known:
        if g.profile not in profiles:
            profiles.append(g.profile)
    if len(profiles) == 1:
        return profiles[0]
    if not profiles:
        return default
    if not interactive or not sys.stdin.isatty():
        return default

    print("Multiple Luanti games detected:", file=sys.stderr)
    for i, g in enumerate(known, 1):
        label = PROFILES.get(g.profile, (g.profile,))[0]
        print(f"  {i}) {g.title}  [{g.game_id}] -> profile {g.profile} ({label})",
              file=sys.stderr)
    while True:
        try:
            choice = input(f"Choose target game [1-{len(known)}] (default 1): ").strip()
        except EOFError:
            return default
        if not choice:
            return known[0].profile
        if choice.isdigit() and 1 <= int(choice) <= len(known):
            return known[int(choice) - 1].profile
        print("Invalid choice.", file=sys.stderr)
