"""
Vanilla Minecraft -> Luanti item mapping.

This is a translation dictionary for *vanilla* materials only.  No mod is ever
hardcoded; mod-specific ids are always passed through using the mod's own
namespace.  The dictionary maps the two supported target games:

    voxelibre  -> VoxeLibre / MineClone2  (mcl_* namespace)
    mtg        -> Minetest Game           (default:* namespace)
"""

from __future__ import annotations

from typing import Optional

# MC path -> {"voxelibre": id, "mtg": id}
VANILLA: dict[str, dict[str, str]] = {
    # --- basic building blocks ---
    "stone": {"voxelibre": "mcl_core:stone", "mtg": "default:stone"},
    "cobblestone": {"voxelibre": "mcl_core:cobble", "mtg": "default:cobble"},
    "mossy_cobblestone": {"voxelibre": "mcl_core:mossycobble", "mtg": "default:mossycobble"},
    "stone_bricks": {"voxelibre": "mcl_core:stonebrick", "mtg": "default:stonebrick"},
    "bricks": {"voxelibre": "mcl_core:brick_block", "mtg": "default:brick"},
    "dirt": {"voxelibre": "mcl_core:dirt", "mtg": "default:dirt"},
    "grass_block": {"voxelibre": "mcl_core:dirt_with_grass", "mtg": "default:dirt_with_grass"},
    "sand": {"voxelibre": "mcl_core:sand", "mtg": "default:sand"},
    "red_sand": {"voxelibre": "mcl_core:redsand", "mtg": "default:sand"},
    "gravel": {"voxelibre": "mcl_core:gravel", "mtg": "default:gravel"},
    "clay": {"voxelibre": "mcl_core:clay", "mtg": "default:clay"},
    "bedrock": {"voxelibre": "mcl_core:bedrock", "mtg": "default:bedrock"},
    "obsidian": {"voxelibre": "mcl_core:obsidian", "mtg": "default:obsidian"},
    "netherrack": {"voxelibre": "mcl_nether:netherrack", "mtg": "default:netherrack"},
    "soul_sand": {"voxelibre": "mcl_nether:soul_sand", "mtg": "default:soulsand"},
    "glowstone": {"voxelibre": "mcl_nether:glowstone", "mtg": "default:glowstone"},
    "end_stone": {"voxelibre": "mcl_end:end_stone", "mtg": "default:stone"},
    "quartz_block": {"voxelibre": "mcl_nether:quartz_block", "mtg": "default:quartz_block"},
    "snow_block": {"voxelibre": "mcl_core:snowblock", "mtg": "default:snowblock"},
    "ice": {"voxelibre": "mcl_core:ice", "mtg": "default:ice"},
    "packed_ice": {"voxelibre": "mcl_core:packed_ice", "mtg": "default:ice"},
    "glass": {"voxelibre": "mcl_core:glass", "mtg": "default:glass"},
    "sandstone": {"voxelibre": "mcl_core:sandstone", "mtg": "default:sandstone"},
    "granite": {"voxelibre": "mcl_core:granite", "mtg": "default:stone"},
    "diorite": {"voxelibre": "mcl_core:diorite", "mtg": "default:stone"},
    "andesite": {"voxelibre": "mcl_core:andesite", "mtg": "default:stone"},
    "tuff": {"voxelibre": "mcl_core:tuff", "mtg": "default:stone"},
    "deepslate": {"voxelibre": "mcl_core:deepslate", "mtg": "default:stone"},
    "cobbled_deepslate": {"voxelibre": "mcl_core:cobbled_deepslate", "mtg": "default:cobble"},
    "basalt": {"voxelibre": "mcl_nether:basalt", "mtg": "default:stone"},
    "blackstone": {"voxelibre": "mcl_nether:blackstone", "mtg": "default:stone"},
    "calcite": {"voxelibre": "mcl_core:calcite", "mtg": "default:stone"},
    # --- ores ---
    "coal_ore": {"voxelibre": "mcl_core:stone_with_coal", "mtg": "default:stone_with_coal"},
    "iron_ore": {"voxelibre": "mcl_core:stone_with_iron", "mtg": "default:stone_with_iron"},
    "gold_ore": {"voxelibre": "mcl_core:stone_with_gold", "mtg": "default:stone_with_gold"},
    "diamond_ore": {"voxelibre": "mcl_core:stone_with_diamond", "mtg": "default:stone_with_diamond"},
    "emerald_ore": {"voxelibre": "mcl_core:stone_with_emerald", "mtg": "default:stone_with_emerald"},
    "lapis_ore": {"voxelibre": "mcl_core:stone_with_lapis", "mtg": "default:stone_with_mese"},
    "redstone_ore": {"voxelibre": "mcl_core:stone_with_redstone", "mtg": "default:stone_with_mese"},
    "copper_ore": {"voxelibre": "mcl_copper:stone_with_copper", "mtg": "default:stone_with_copper"},
    "deepslate_coal_ore": {"voxelibre": "mcl_core:deepslate_with_coal", "mtg": "default:stone_with_coal"},
    "deepslate_iron_ore": {"voxelibre": "mcl_core:deepslate_with_iron", "mtg": "default:stone_with_iron"},
    "deepslate_diamond_ore": {"voxelibre": "mcl_core:deepslate_with_diamond", "mtg": "default:stone_with_diamond"},
    "deepslate_gold_ore": {"voxelibre": "mcl_core:deepslate_with_gold", "mtg": "default:stone_with_gold"},
    "deepslate_copper_ore": {"voxelibre": "mcl_copper:deepslate_with_copper", "mtg": "default:stone_with_copper"},
    # --- ingots / materials ---
    "coal": {"voxelibre": "mcl_core:coal_lump", "mtg": "default:coal_lump"},
    "charcoal": {"voxelibre": "mcl_core:charcoal_lump", "mtg": "default:coal_lump"},
    "iron_ingot": {"voxelibre": "mcl_core:iron_ingot", "mtg": "default:steel_ingot"},
    "gold_ingot": {"voxelibre": "mcl_core:gold_ingot", "mtg": "default:gold_ingot"},
    "copper_ingot": {"voxelibre": "mcl_copper:copper_ingot", "mtg": "default:copper_ingot"},
    "netherite_ingot": {"voxelibre": "mcl_nether:netherite_ingot", "mtg": "default:steel_ingot"},
    "iron_nugget": {"voxelibre": "mcl_core:iron_nugget", "mtg": "default:iron_nugget"},
    "gold_nugget": {"voxelibre": "mcl_core:gold_nugget", "mtg": "default:gold_nugget"},
    "diamond": {"voxelibre": "mcl_core:diamond", "mtg": "default:diamond"},
    "emerald": {"voxelibre": "mcl_core:emerald", "mtg": "default:emerald"},
    "lapis_lazuli": {"voxelibre": "mcl_core:lapis", "mtg": "default:mese_crystal"},
    "redstone": {"voxelibre": "mcl_redstone:redstone", "mtg": "default:mese_crystal_fragment"},
    "quartz": {"voxelibre": "mcl_nether:quartz", "mtg": "default:quartz_crystal"},
    "flint": {"voxelibre": "mcl_core:flint", "mtg": "default:flint"},
    "gunpowder": {"voxelibre": "mcl_mobitems:gunpowder", "mtg": "tnt:gunpowder"},
    "string": {"voxelibre": "mcl_mobitems:string", "mtg": "farming:string"},
    "stick": {"voxelibre": "mcl_core:stick", "mtg": "group:stick"},
    "bone": {"voxelibre": "mcl_mobitems:bone", "mtg": "bones:bone"},
    "bone_meal": {"voxelibre": "mcl_dye:white", "mtg": "farming:bonemeal"},
    "leather": {"voxelibre": "mcl_mobitems:leather", "mtg": "mobs:leather"},
    "clay_ball": {"voxelibre": "mcl_core:clay_lump", "mtg": "default:clay_lump"},
    "brick": {"voxelibre": "mcl_core:brick", "mtg": "default:brick"},
    "paper": {"voxelibre": "mcl_core:paper", "mtg": "default:paper"},
    "book": {"voxelibre": "mcl_books:book", "mtg": "default:book"},
    "wheat": {"voxelibre": "mcl_farming:wheat_item", "mtg": "farming:wheat"},
    "wheat_seeds": {"voxelibre": "mcl_farming:wheat_seeds", "mtg": "farming:seed_wheat"},
    "sugar": {"voxelibre": "mcl_core:sugar", "mtg": "farming:sugar"},
    "slime_ball": {"voxelibre": "mcl_mobitems:slimeball", "mtg": "mobs:slime_ball"},
    "egg": {"voxelibre": "mcl_mobitems:egg", "mtg": "mobs:egg"},
    "feather": {"voxelibre": "mcl_mobitems:feather", "mtg": "mobs:feather"},
    # --- planks / logs (wood, uses group for planks) ---
    "oak_planks": {"voxelibre": "mcl_core:wood", "mtg": "default:wood"},
    "oak_log": {"voxelibre": "mcl_core:tree", "mtg": "default:tree"},
    "oak_leaves": {"voxelibre": "mcl_core:leaves", "mtg": "default:leaves"},
    "oak_sapling": {"voxelibre": "mcl_core:sapling", "mtg": "default:sapling"},
    # --- tools (items) ---
    "wooden_pickaxe": {"voxelibre": "mcl_tools:pick_wood", "mtg": "default:pick_wood"},
    "stone_pickaxe": {"voxelibre": "mcl_tools:pick_stone", "mtg": "default:pick_stone"},
    "iron_pickaxe": {"voxelibre": "mcl_tools:pick_iron", "mtg": "default:pick_steel"},
    "diamond_pickaxe": {"voxelibre": "mcl_tools:pick_diamond", "mtg": "default:pick_diamond"},
    "iron_axe": {"voxelibre": "mcl_tools:axe_iron", "mtg": "default:axe_steel"},
    "iron_shovel": {"voxelibre": "mcl_tools:shovel_iron", "mtg": "default:shovel_steel"},
    "iron_sword": {"voxelibre": "mcl_tools:sword_iron", "mtg": "default:sword_steel"},
    "bucket": {"voxelibre": "mcl_buckets:bucket_empty", "mtg": "bucket:bucket_empty"},
    "water_bucket": {"voxelibre": "mcl_buckets:bucket_water", "mtg": "bucket:bucket_water"},
    "lava_bucket": {"voxelibre": "mcl_buckets:bucket_lava", "mtg": "bucket:bucket_lava"},
    "tnt": {"voxelibre": "mcl_tnt:tnt", "mtg": "tnt:tnt"},
    "torch": {"voxelibre": "mcl_torches:torch", "mtg": "default:torch"},
    "chest": {"voxelibre": "mcl_chests:chest", "mtg": "default:chest"},
    "crafting_table": {"voxelibre": "mcl_crafting_table:crafting_table", "mtg": "default:crafting_table"},
    "furnace": {"voxelibre": "mcl_furnaces:furnace", "mtg": "default:furnace"},
    "bookshelf": {"voxelibre": "mcl_books:bookshelf", "mtg": "default:bookshelf"},
    "ladder": {"voxelibre": "mcl_core:ladder", "mtg": "default:ladder_wood"},
}

# MC item/block tag -> Luanti "group:..." name (used for recipe ingredients).
TAG_TO_GROUP: dict[str, str] = {
    "minecraft:planks": "group:wood",
    "minecraft:logs": "group:tree",
    "minecraft:logs_that_burn": "group:tree",
    "minecraft:stone": "group:stone",
    "minecraft:coals": "group:coal",
    "minecraft:wool": "group:wool",
    "minecraft:wooden_slabs": "group:wood",
    "minecraft:wooden_buttons": "group:wood",
    "minecraft:wooden_fences": "group:wood",
    "minecraft:wooden_stairs": "group:wood",
    "minecraft:leaves": "group:leaves",
    "minecraft:sand": "group:sand",
    "minecraft:flowers": "group:flower",
    "minecraft:saplings": "group:sapling",
    "c:planks": "group:wood",
    "c:wooden_planks": "group:wood",
    "c:logs": "group:tree",
    "c:ingots": "group:metal",
    "c:ores": "group:stone",
    "c:stones": "group:stone",
    "c:glass_blocks": "group:glass",
}


def map_vanilla(path: str, game: str = "voxelibre") -> Optional[str]:
    entry = VANILLA.get(path)
    if not entry:
        return None
    return entry.get(game)


def tag_to_group(tag: str) -> Optional[str]:
    return TAG_TO_GROUP.get(tag)
