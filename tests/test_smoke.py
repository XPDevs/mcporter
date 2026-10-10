"""Self-contained smoke tests for mcporter.

These build tiny synthetic Minecraft mods in a temporary directory (no network,
no external jars, no bundled assets) and run the full translation pipeline over
them, then assert that a syntactically valid Luanti mod was produced.

Run with:

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import port  # noqa: E402
from mcporter import luacheck, util  # noqa: E402
from mcporter import games as games_mod  # noqa: E402


def _minimal_png() -> bytes:
    """A valid 1x1 PNG (built by hand, no dependencies)."""
    from mcporter import png as png_mod

    img = png_mod.Image(1, 1, bytearray([255, 0, 0, 255]))
    return png_mod.encode(img)


def build_fabric_jar(path: str, modid: str = "testmod",
                     name: str = "Test Mod") -> None:
    meta = {
        "schemaVersion": 1,
        "id": modid,
        "version": "1.0.0",
        "name": name,
        "description": "A tiny synthetic mod used by the test-suite.",
        "authors": ["Test Author"],
        "license": "MIT",
        "depends": {"minecraft": ">=1.20 <1.22"},
        "entrypoints": {"main": [f"com.example.{modid}.ExampleMod"]},
    }
    lang = {
        "block.testmod.testblock": "Test Block",
        "item.testmod.testingot": "Test Ingot",
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("fabric.mod.json", json.dumps(meta))
        z.writestr(f"assets/{modid}/lang/en_us.json", json.dumps(lang))
        z.writestr(f"assets/{modid}/textures/block/testblock.png", _minimal_png())
        z.writestr(f"assets/{modid}/textures/item/testingot.png", _minimal_png())
        z.writestr(f"assets/{modid}/blockstates/testblock.json",
                   json.dumps({"variants": {"": {"model": f"{modid}:block/testblock"}}}))
        z.writestr(f"assets/{modid}/models/block/testblock.json",
                   json.dumps({"parent": "block/cube_all",
                               "textures": {"all": f"{modid}:block/testblock"}}))
        z.writestr(f"assets/{modid}/models/item/testingot.json",
                   json.dumps({"parent": "item/generated",
                               "textures": {"layer0": f"{modid}:item/testingot"}}))


class TranslationSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mcporter_test_")
        self.jar = os.path.join(self.tmp, "TestMod-1.0.0.jar")
        build_fabric_jar(self.jar)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_identify(self):
        from mcporter.detect import detect
        from mcporter.jarfs import VirtualFS

        info = detect(VirtualFS(self.jar))
        self.assertEqual(info.modid, "testmod")
        self.assertEqual(info.name, "Test Mod")
        self.assertEqual(info.loader, "fabric")
        self.assertIn("1.20", " ".join(info.mc_versions))

    def test_port_produces_valid_mod(self):
        out = os.path.join(self.tmp, "out")
        report = port.port(
            self.jar, out, "voxelibre",
            "/nonexistent/client.jar",  # force placeholder textures, no deps
            quiet=True, no_logic=False, install=False, mods_dir=None,
        )
        # core files exist
        for rel in ("mod.conf", "init.lua", "blocks.lua", "items.lua", "recipes.lua"):
            self.assertTrue(os.path.isfile(os.path.join(out, rel)), rel)
        self.assertTrue(os.path.isfile(os.path.join(out, "TRANSLATION_REPORT.md")))
        # the built-in Lua syntax check must pass
        self.assertFalse(luacheck.check_mod(out))
        self.assertFalse(report["lua_check"])
        # the mod name is carried through
        with open(os.path.join(out, "mod.conf"), encoding="utf-8") as fh:
            conf = fh.read()
        self.assertIn("name = testmod", conf)
        self.assertIn("Test Mod", conf)
        # the block/item we declared should have been discovered
        with open(os.path.join(out, "blocks.lua"), encoding="utf-8") as fh:
            blocks = fh.read()
        self.assertIn("testblock", blocks)

    def test_default_outdir_is_mod_name(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            port.port(self.jar, None, "voxelibre", "/nonexistent/client.jar",
                      quiet=True, no_logic=True, install=False, mods_dir=None)
            expected = port.safe_folder_name("Test Mod", "testmod")
            self.assertTrue(os.path.isdir(os.path.join(self.tmp, expected)))
        finally:
            os.chdir(cwd)

    def test_datapack_is_report_only(self):
        dp = os.path.join(self.tmp, "TestData.zip")
        with zipfile.ZipFile(dp, "w") as z:
            z.writestr("pack.mcmeta", json.dumps(
                {"pack": {"pack_format": 15, "description": "test data"}}))
            z.writestr("data/test/structures/hut.nbt", b"\x00")
        from mcporter.detect import detect
        from mcporter.jarfs import VirtualFS
        ident = detect(VirtualFS(dp))
        self.assertIn(ident.loader, ("datapack", "resourcepack", "unknown"))


class HelpersTest(unittest.TestCase):
    def test_lua_quote(self):
        self.assertEqual(util.lua_quote("a'b"), '"a\'b"')
        self.assertEqual(util.lua_quote('say "hi"'), '"say \\"hi\\""')

    def test_expand_inputs_single_mod_dir(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "fabric.mod.json"), "w") as fh:
                fh.write("{}")
            inputs, batch = port.expand_inputs([d])
            self.assertEqual(inputs, [d])
            self.assertFalse(batch)

    def test_expand_inputs_folder_of_mods(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("a.jar", "b.jar"):
                with zipfile.ZipFile(os.path.join(d, n), "w") as z:
                    z.writestr("fabric.mod.json", "{}")
            inputs, batch = port.expand_inputs([d])
            self.assertEqual(len(inputs), 2)
            self.assertTrue(batch)


class GameDetectionTest(unittest.TestCase):
    def test_profiles_present(self):
        self.assertIn("voxelibre", games_mod.PROFILES)
        self.assertIn("mtg", games_mod.PROFILES)

    def test_choose_game_defaults_without_games(self):
        self.assertEqual(games_mod.choose_game([], interactive=False), "voxelibre")

    def test_choose_game_single_profile(self):
        g = games_mod.InstalledGame(
            game_id="mineclonia", title="Mineclonia", path="/x",
            profile="voxelibre", mods_seen=())
        self.assertEqual(games_mod.choose_game([g], interactive=False), "voxelibre")


if __name__ == "__main__":
    unittest.main()
