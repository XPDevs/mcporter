"""
mcporter - a from-scratch, pure-Python Minecraft -> Luanti mod translation toolkit.

No third-party dependencies. Everything (zip access, PNG decoding/encoding,
Java .class parsing, JSON recipe/model parsing, Lua generation) is implemented
here on top of the Python standard library.

The design goal is *best-effort static translation* of arbitrary Minecraft
mods into playable Luanti/VoxeLibre/MineClone mods:

    assets   (lang / textures / models / sounds)  -> copied + remapped
    registry (blocks / items / tools / food)       -> register_node / register_craftitem
    recipes  (crafting / cooking / stonecutting)   -> register_craft
    loot     (block drops)                         -> node drop tables
    text     (all shipped locales)                 -> Luanti locale/*.tr

Anything that requires runtime Java (custom entities, GUIs, networking,
client rendering, mixins, redstone logic, ...) cannot be translated by static
analysis and is instead *reported* with a confidence rating so a human can
finish the port. See mcporter/emit.py and mcporter/report.py.
"""

__version__ = "0.1.0"
