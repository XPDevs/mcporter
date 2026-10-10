# mcporter

**Translate Minecraft: Java Edition mods into playable [Luanti](https://www.luanti.org/) mods, from scratch, in pure Python, with zero dependencies.**

`mcporter` reads any Minecraft Java mod (Fabric, Quilt, Forge, NeoForge, legacy
Forge, LiteLoader, datapacks, resource packs and Bedrock packs). It figures out
what it contains, and writes out a Luanti mod targeting the game you actually
have installed (VoxeLibre / MineClone or Minetest Game).

It is a **best-effort static translator**, not magic: everything that can be
recovered from *data* (blocks, items, recipes, textures, models, sounds,
translations, loot) is ported automatically, and everything that needs the
Java runtime (entities, GUIs, networking, rendering, mixins) is **reported**
with a confidence rating so a human can finish the job. On top of that it
produces a best-effort **Java bytecode → Lua reference translation** of the
mod's own classes, so you can see and reuse the original logic. See
[What gets ported](#what-gets-ported).

> **WARNING. READ BEFORE YOU SHARE ANYTHING**
>
> `mcporter` is a **personal conversion tool**. A converted/ported mod is a
> **derivative work** of the original mod, and it usually contains the original
> author's textures, models, sounds, code, names and other creative work.
>
> **Do NOT publish, upload, redistribute or share a converted mod unless the
> original author has clearly given permission for it to be redistributed
> (including in converted/ported form).** Always read and follow the original
> mod's license and the author's stated rules. Many licenses (and Mojang's own
> asset rules) forbid redistribution, and some forbid derivative works
> entirely. When in doubt, **ask the original author first** and keep your
> conversion private. See [Legal, licensing & liability](#legal-licensing--liability)
> below.

---

## Features

- **Automatic mod identification.** No hard-coded mod list. Reads
  `fabric.mod.json`, `quilt.mod.json`, `META-INF/neoforge.mods.toml`,
  `META-INF/mods.toml`, `mcmod.info`, `litemod.json`, `manifest.json` and
  `pack.mcmeta`, including nested/`src/main/resources` source trees.
- **Most Minecraft versions & loaders.** Fabric, Quilt, Forge, NeoForge,
  legacy Forge (1.12 and older), LiteLoader, datapacks, resource packs and
  Bedrock packs, from a compiled `.jar`/`.zip` **or** an unpacked source tree.
- **Blocks & items.** Discovered from `assets/` (language keys, blockstates,
  models) *and* from the compiled bytecode, then registered as
  `core.register_node` / `core.register_craftitem`, including tools and food.
- **Recipes.** Crafting (shaped/shapeless), cooking/smelting, stonecutting and
  more, translated to `core.register_craft` against a Minecraft→Luanti id map.
- **Textures, models & sounds.** Copied and remapped; missing textures become
  generated placeholders so the mod never crashes.
- **Loot tables.** Block drops folded into node drop tables.
- **Translations.** Every shipped locale becomes a Luanti `locale/*.tr`.
- **Java → Lua translator.** A full JVM class-file parser and bytecode
  decoder that emits readable Lua for the mod's own classes.
- **Targets your installed game.** Detects VoxeLibre / MineClone / Minetest
  Game on Linux, macOS and Windows (including Flatpak and Snap) and adapts the
  generated ids and dependencies.
- **Batch mode.** Point it at a folder of mods and it converts them all.
- **One folder per mod.** The output folder is named after the mod.
- **A report for every port.** `TRANSLATION_REPORT.md` plus machine-readable
  `.mcporter_report.json`, including a translation score and the list of Java
  systems that still need manual work.

## Requirements

- **Python 3.10 or newer.** That is the only requirement. The standard library
  is used for everything (zip access, PNG decode/encode, class-file parsing,
  JSON/TOML parsing, Lua generation).
- Optionally, a Minecraft `client.jar` to copy vanilla textures/models that a
  mod references but does not ship. The tool looks for
  `./minecraft/client.jar`, then the `MC_CLIENT_JAR` environment variable, then
  falls back to placeholders.
- Luanti is only needed to *play* the output, not to convert.

## Install / run

There is nothing to install; clone and run.

```bash
git clone https://github.com/XPDevs/mcporter.git
cd mcporter

# Linux / macOS
./run.sh /path/to/SomeMod.jar

# Windows
run.bat "C:\path\to\SomeMod.jar"
```

Or call the CLI directly:

```bash
python3 port.py /path/to/SomeMod.jar
```

Run it with **no arguments** and it will ask you for the mod path and, when it
cannot decide, which installed game to target:

```bash
./run.sh
# Enter the path to a Minecraft mod (.jar, .zip, .litemod, or a folder):
```

You can also install it as a console command:

```bash
pip install .
mcporter /path/to/SomeMod.jar
```

## Usage

```
mcporter <input...> [options]

  input                 a mod .jar/.zip/.litemod, an extracted dir, a source
                        tree, or a folder full of mods (batch mode)

  -o, --out DIR         output directory
                        (default: a folder named after the mod, in the cwd)
  --game PROFILE        auto | voxelibre | mtg        (default: auto)
  --game-path DIR       extra directory to search for installed Luanti games
  --vanilla PATH        a Minecraft client.jar for vanilla assets
  --no-logic            skip the Java bytecode -> Lua translation pass
  --install             copy the finished mod into the detected Luanti mods/
  -y, --yes             non-interactive; never prompt
  --json                print the JSON report(s) to stdout
  --quiet               suppress progress output
  --version             print the version and exit
```

### Examples

```bash
# Convert one mod; output goes to ./SomeMod/
./run.sh ~/Downloads/SomeMod.jar

# Target VoxeLibre explicitly and install it into your Luanti mods/ folder
./run.sh ~/Downloads/SomeMod.jar --game voxelibre --install

# Convert an entire folder of mods at once
./run.sh ~/.minecraft/mods

# Convert an unpacked Gradle source tree (no jar needed)
./run.sh ~/dev/MyMod

# Skip the experimental Java->Lua pass
./run.sh SomeMod.zip --no-logic

# Machine-readable output for scripting
./run.sh SomeMod.jar --json --quiet

# Non-interactive / CI
./run.sh SomeMod.jar -y --game mtg
```

Once converted, drop the output folder into your Luanti world's `worldmods/`
(or the global `mods/`) directory and enable it, or let `--install` do it.

## What gets ported

| Minecraft content                | Luanti result                                   |
| -------------------------------- | ----------------------------------------------- |
| Blocks                           | `register_node` (with node boxes/collision)     |
| Items                            | `register_craftitem`                            |
| Tools & armour                   | `register_tool` / `register_craftitem`          |
| Food                             | craftitem with `on_use` groups                  |
| Crafting / cooking / stonecut    | `register_craft` recipes                        |
| Block loot tables                | node `drop` tables                              |
| Textures / models                | copied + remapped (placeholders if missing)     |
| Sounds                           | copied into `sounds/`                           |
| `lang/*.json`                    | `locale/*.tr`                                   |
| Java classes                     | `logic/*.lua` best-effort reference translation |

## What is *reported* rather than ported

Static analysis cannot run Java, so these are listed in the report with a
confidence rating and a reason. They are the manual work:

- custom entities, mob AI, projectiles;
- GUIs / screens / containers;
- networking / packets;
- client-side rendering, particles, shaders;
- mixins and bytecode manipulation;
- complex redstone and tick logic;
- datapack worldgen / structures.

## The Java → Lua translator

`mcporter/j2l.py` parses the JVM class file format (constant pool, methods,
the `Code` attribute) and decodes bytecode into a small symbolic stack machine,
then prints Lua. It recovers:

- constants, local loads/stores;
- `static`/instance field access;
- `invokestatic` / `invokevirtual` / `invokespecial` / `invokeinterface`;
- arithmetic and the `bit` library for integer bit-ops;
- array creation, loads and stores;
- returns and comparisons (as annotated `goto` comments).

Because Luanti's Lua has no `goto`, branches are emitted as comments:

```lua
-- if v6:hasNext() == 0 then goto @42 end
```

The result is **not** a drop-in runtime implementation. It is a readable map
of the original logic that loads defensively (`pcall`) and never breaks the
data port. If a class fails to translate, it is skipped silently.

## How it works

```
port.py                  CLI: input expansion, game detection, orchestration
mcporter/
  jarfs.py               virtual filesystem over .jar/.zip/dir/source trees
  detect.py              identify the mod & loader across all metadata formats
  assets.py              asset/lang/model/texture index (+ vanilla fallback)
  vanilla_map.py         Minecraft -> Luanti name/id mapping
  registry.py            discover blocks/items/tools/food (assets + bytecode)
  recipes.py             recipe + tag translation
  loot.py                loot-table -> node drop translation
  classfile.py           JVM .class parser (constant pool, Code attribute)
  j2l.py                 JVM bytecode decoder -> Lua reference translation
  emit.py                write the Luanti mod (init/blocks/items/recipes/...)
  report.py              TRANSLATION_REPORT.md + .mcporter_report.json
  luacheck.py            dependency-free Lua syntax sanity check
  png.py                 PNG decode/encode/composite (stdlib only)
  games.py               detect installed Luanti games & pick a profile
  util.py                small helpers (json, lua quoting, sanitising)
```

## Development

```bash
# run the test-suite (builds tiny synthetic mods; no network, no assets)
python3 -m unittest discover -s tests -v

# byte-compile everything
python3 -m py_compile port.py mcporter/*.py
```

The tests create minimal Fabric/datapack archives on the fly and assert that
the full pipeline produces a syntactically valid mod, so no downloaded mods or
vanilla jars are required.

## Contributing

Issues and pull requests are welcome. If a specific mod converts badly, open an
issue with the mod name, its Minecraft version, the loader, and the generated
`TRANSLATION_REPORT.md`. That report is designed to make problems reproducible.

## License

The `mcporter` *software itself* is released under the [MIT License](LICENSE).
That license covers **only this tool's source code**. It does **not** grant you
any rights to the Minecraft mods you run through it, nor to anything the tool
produces from them.

## Legal, licensing & liability

**This section is a plain-language summary, not legal advice. If you plan to
distribute anything, consult a qualified lawyer in your jurisdiction.**

### 1. Converted mods are derivative works, so you need permission to share them

A mod produced by `mcporter` is a derivative work of the original Minecraft mod.
It typically embeds or reproduces the original author's textures, models,
sounds, music, language files, code, names and other creative work.

- **Do not distribute, publish, upload, mirror, sell or otherwise share a
  converted mod unless the original author has explicitly allowed it.**
- **Read and obey the original mod's license** (for example All Rights
  Reserved, CC-BY-NC, GPL, MIT, and so on) and **the author's stated rules**,
  including any rules about ports/conversions, credit, commercial use,
  modification, or redistribution.
- Some licenses **forbid derivative works or redistribution entirely**; many
  authors require you to **ask for permission first**. If the license is
  unclear or says "All Rights Reserved", assume you may **not** share your
  conversion.
- Give proper **credit** to the original author wherever they require it.
- Remember that Minecraft's own assets and terms are owned by Mojang/Microsoft
  and are subject to their rules as well.

**The safe default: keep your conversion private.** Use it for yourself. If you
want to share it, contact the original author, explain what you did, and get
their permission in writing before you post it anywhere.

### 2. No warranty

`mcporter` and everything it produces are provided **"as is", without warranty
of any kind**, express or implied, including but not limited to the warranties
of merchantability, fitness for a particular purpose, title and
non-infringement. The tool is experimental, best-effort and may be wrong,
incomplete, or produce broken output.

### 3. Limitation of liability

To the maximum extent permitted by applicable law, **XPDevs (the author of
`mcporter`) and any contributors accept no liability and no responsibility
whatsoever** for:

- any use or misuse of this tool;
- any copyright, trademark, license or other intellectual-property
  infringement you commit (or that arises) by running this tool or by
  distributing anything it produces;
- any legal claims, takedown requests, DMCA notices, bans, account
  terminations, damages, losses, costs or expenses of any kind; and
- any direct, indirect, incidental, special, consequential or punitive damages
  arising out of or in connection with the tool or its output.

**You, the user, are solely and entirely responsible** for how you use
`mcporter`, for the mods you convert, and for anything you choose to do with
the results, including obtaining any and all permissions and complying with
all applicable licenses and laws. By using this tool you accept these terms.

### 4. Not affiliated

`mcporter` is an independent project maintained by **XPDevs**
(https://github.com/XPDevs). It is **not affiliated with, endorsed by, or
sponsored by** Mojang, Microsoft, the Luanti project, or any Minecraft mod
author. "Minecraft" is a trademark of Mojang Synergies AB. "Luanti" and
"Minetest" belong to their respective owners. All mod names, trademarks and
copyrights belong to their respective owners.
