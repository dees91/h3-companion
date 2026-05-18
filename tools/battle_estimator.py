#!/usr/bin/env python3
"""
VCMI Battle Estimator
=====================
Symulator bitwy Monte Carlo oparty na formule obrażeń z VCMI
(lib/battle/DamageCalculator.cpp) z kompletną bazą ~150 stworzeń z Heroes III.

Użycie:
    python3 tools/battle_estimator.py "10 pikeman, 2 griffin" vs "lot of boar"
    python3 tools/battle_estimator.py "5 archangel" vs "horde of black dragon"
    python3 tools/battle_estimator.py "100 skeleton, 20 vampire lord" vs "30 champion"
    python3 tools/battle_estimator.py --list                   # lista stworzeń
    python3 tools/battle_estimator.py --list castle             # stworzenia Castle
    python3 tools/battle_estimator.py "10 pikeman" vs "20 boar" -v  # verbose
"""

import argparse
import random
import math
import re
import sys
from dataclasses import dataclass
from typing import List, Tuple, Optional


# ---------------------------------------------------------------------------
# Stałe z VCMI: config/gameConfig.json (linie 600-606)
# ---------------------------------------------------------------------------
ATTACK_POINT_DAMAGE_FACTOR = 0.05
ATTACK_POINT_DAMAGE_FACTOR_CAP = 4.0
DEFENSE_POINT_DAMAGE_FACTOR = 0.025
DEFENSE_POINT_DAMAGE_FACTOR_CAP = 0.7


# ---------------------------------------------------------------------------
# Progi ilościowe z CCreatureHandler.cpp (linie 237-257)
# ---------------------------------------------------------------------------
QUANTITY_DESCRIPTORS = {
    "few":     (1, 4),
    "several": (5, 9),
    "pack":    (10, 19),
    "lots":    (20, 49),
    "horde":   (50, 99),
    "throng":  (100, 249),
    "swarm":   (250, 499),
    "zounds":  (500, 999),
    "legion":  (1000, 1500),
}


# ---------------------------------------------------------------------------
# Definicja stworzenia (odpowiednik CCreature w VCMI)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Creature:
    name: str
    faction: str
    level: int
    attack: int
    defense: int
    min_damage: int
    max_damage: int
    hit_points: int
    speed: int
    ai_value: int
    shots: int = 0          # 0 = melee
    retaliations: int = 1
    no_retaliation: bool = False   # attacker causes no enemy retaliation
    double_strike: bool = False
    flying: bool = False
    # NOTE: zdolności jak life drain, regeneration, petrify, breath attack
    # nie są modelowane w uproszczonej symulacji

    @property
    def shooter(self) -> bool:
        return self.shots > 0


# ---------------------------------------------------------------------------
# Kompletna baza stworzeń — kanoniczne wartości z Heroes III (CRTRAITS.TXT)
# Źródło: lib/CCreatureHandler.cpp::loadLegacyData(), config/creatures/*.json
# ---------------------------------------------------------------------------
CREATURES = [
    # ===== CASTLE (config/creatures/castle.json) =====
    Creature("Pikeman",           "Castle",     1,  4,  5,  1,  3,  10, 4,    80),
    Creature("Halberdier",        "Castle",     1,  6,  5,  2,  3,  10, 5,   115),
    Creature("Archer",            "Castle",     2,  6,  3,  2,  3,  10, 4,   126, shots=12),
    Creature("Marksman",          "Castle",     2,  6,  3,  2,  3,  10, 6,   184, shots=24),
    Creature("Griffin",           "Castle",     3,  8,  8,  3,  6,  25, 6,   351, retaliations=2, flying=True),
    Creature("Royal Griffin",     "Castle",     3,  9,  9,  3,  6,  25, 9,   448, retaliations=99, flying=True),
    Creature("Swordsman",        "Castle",     4, 10, 12,  6,  9,  35, 5,   445),
    Creature("Crusader",          "Castle",     4, 12, 12,  7, 10,  35, 6,   588, double_strike=True),
    Creature("Monk",              "Castle",     5, 12,  7, 10, 12,  30, 5,   582, shots=12),
    Creature("Zealot",            "Castle",     5, 12, 10, 10, 12,  30, 7,   750, shots=24),
    Creature("Cavalier",          "Castle",     6, 15, 15, 15, 25, 100, 7,  1946),
    Creature("Champion",          "Castle",     6, 16, 16, 20, 25, 100, 9,  2100),
    Creature("Angel",             "Castle",     7, 20, 20, 50, 50, 200, 12, 5019, flying=True),
    Creature("Archangel",         "Castle",     7, 30, 30, 50, 50, 250, 18, 8776, flying=True),

    # ===== RAMPART (config/creatures/rampart.json) =====
    Creature("Centaur",           "Rampart",    1,  6,  3,  1,  2,   8, 6,   100),
    Creature("Centaur Captain",   "Rampart",    1,  6,  3,  1,  2,  10, 8,   138),
    Creature("Dwarf",             "Rampart",    2,  6,  7,  2,  4,  20, 3,   138),
    Creature("Battle Dwarf",      "Rampart",    2,  7,  7,  2,  4,  20, 5,   209),
    Creature("Wood Elf",          "Rampart",    3,  9,  5,  3,  5,  15, 6,   234, shots=24),
    Creature("Grand Elf",         "Rampart",    3,  9,  5,  3,  5,  15, 7,   331, shots=24, double_strike=True),
    Creature("Pegasus",           "Rampart",    4,  9,  8,  5,  9,  30, 8,   518, flying=True),
    Creature("Silver Pegasus",    "Rampart",    4,  9, 10,  5,  9,  30, 12,  532, flying=True),
    Creature("Dendroid Guard",    "Rampart",    5,  9, 12, 10, 14,  55, 3,   517),
    Creature("Dendroid Soldier",  "Rampart",    5,  9, 12, 10, 14,  65, 4,   803),
    Creature("Unicorn",           "Rampart",    6, 15, 14, 18, 22,  90, 7,  1806),
    Creature("War Unicorn",       "Rampart",    6, 15, 14, 18, 22, 110, 9,  2030),
    Creature("Green Dragon",      "Rampart",    7, 18, 18, 40, 50, 180, 10, 4872, flying=True),
    Creature("Gold Dragon",       "Rampart",    7, 27, 27, 40, 50, 250, 16, 8613, flying=True),

    # ===== TOWER (config/creatures/tower.json) =====
    Creature("Gremlin",           "Tower",      1,  3,  3,  1,  2,   4, 4,    44),
    Creature("Master Gremlin",    "Tower",      1,  3,  3,  1,  2,   4, 5,    66, shots=8),
    Creature("Stone Gargoyle",    "Tower",      2,  6,  6,  2,  3,  16, 6,   165, flying=True),
    Creature("Obsidian Gargoyle", "Tower",      2,  7,  7,  2,  3,  16, 9,   201, flying=True),
    Creature("Stone Golem",       "Tower",      3,  7, 10,  4,  5,  30, 3,   250),
    Creature("Iron Golem",        "Tower",      3,  9, 10,  4,  5,  35, 5,   412),
    Creature("Mage",              "Tower",      4, 11,  8,  7,  9,  25, 5,   570, shots=24),
    Creature("Arch Mage",         "Tower",      4, 12,  9,  7,  9,  30, 7,   680, shots=24),
    Creature("Genie",             "Tower",      5, 12, 12, 13, 16,  40, 7,   884, flying=True),
    Creature("Master Genie",      "Tower",      5, 12, 12, 13, 16,  40, 11,  942, flying=True),
    Creature("Naga",              "Tower",      6, 16, 13, 20, 20, 110, 5,  2016, no_retaliation=True),
    Creature("Naga Queen",        "Tower",      6, 16, 13, 30, 30, 110, 7,  2840, no_retaliation=True),
    Creature("Giant",             "Tower",      7, 19, 16, 40, 60, 150, 7,  3718),
    Creature("Titan",             "Tower",      7, 24, 24, 40, 60, 300, 11, 7500, shots=24),

    # ===== INFERNO (config/creatures/inferno.json) =====
    Creature("Imp",               "Inferno",    1,  2,  3,  1,  2,   4, 5,    50),
    Creature("Familiar",          "Inferno",    1,  4,  4,  1,  2,   4, 7,    60),
    Creature("Gog",               "Inferno",    2,  6,  4,  2,  4,  13, 4,   159, shots=12),
    Creature("Magog",             "Inferno",    2,  7,  4,  2,  4,  13, 6,   240, shots=24),
    Creature("Hell Hound",        "Inferno",    3, 10,  6,  2,  7,  25, 7,   357),
    Creature("Cerberus",          "Inferno",    3, 10,  8,  2,  7,  25, 8,   392, no_retaliation=True),
    Creature("Demon",             "Inferno",    4, 10, 10,  7,  9,  35, 5,   445),
    Creature("Horned Demon",      "Inferno",    4, 10, 10,  7,  9,  40, 6,   480),
    Creature("Pit Fiend",         "Inferno",    5, 13, 13, 13, 17,  45, 7,   765),
    Creature("Pit Lord",          "Inferno",    5, 13, 13, 13, 17,  45, 7,  1224),
    Creature("Efreet",            "Inferno",    6, 16, 12, 16, 24,  90, 9,  1670, flying=True),
    Creature("Efreet Sultan",     "Inferno",    6, 16, 14, 16, 24,  90, 13, 1848, flying=True),
    Creature("Devil",             "Inferno",    7, 19, 21, 30, 40, 160, 11, 5101, flying=True, no_retaliation=True),
    Creature("Arch Devil",        "Inferno",    7, 26, 28, 30, 40, 200, 17, 7115, flying=True, no_retaliation=True),

    # ===== NECROPOLIS (config/creatures/necropolis.json) =====
    Creature("Skeleton",          "Necropolis", 1,  5,  4,  1,  3,   6, 4,    75),
    Creature("Skeleton Warrior",  "Necropolis", 1,  6,  6,  1,  3,   6, 5,    85),
    Creature("Walking Dead",      "Necropolis", 2,  5,  5,  2,  3,  15, 3,    98),
    Creature("Zombie",            "Necropolis", 2,  5,  5,  2,  3,  20, 4,   128),
    Creature("Wight",             "Necropolis", 3,  7,  7,  3,  5,  18, 5,   252, flying=True),
    Creature("Wraith",            "Necropolis", 3,  7,  7,  3,  5,  18, 7,   315, flying=True),
    Creature("Vampire",           "Necropolis", 4, 10,  9,  5,  8,  30, 6,   555, flying=True, no_retaliation=True),
    Creature("Vampire Lord",      "Necropolis", 4, 10, 10,  5,  8,  40, 9,   783, flying=True, no_retaliation=True),
    Creature("Lich",              "Necropolis", 5, 13, 10, 11, 13,  30, 6,   848, shots=12),
    Creature("Power Lich",        "Necropolis", 5, 13, 10, 11, 15,  40, 7,  1079, shots=24),
    Creature("Black Knight",      "Necropolis", 6, 16, 16, 15, 30, 120, 7,  2087),
    Creature("Dread Knight",      "Necropolis", 6, 18, 18, 15, 30, 120, 9,  2382, double_strike=True),
    Creature("Bone Dragon",       "Necropolis", 7, 17, 15, 25, 50, 150, 9,  3388, flying=True),
    Creature("Ghost Dragon",      "Necropolis", 7, 19, 17, 25, 50, 200, 14, 4696, flying=True),

    # ===== DUNGEON (config/creatures/dungeon.json) =====
    Creature("Troglodyte",        "Dungeon",    1,  4,  3,  1,  3,   5, 4,    59),
    Creature("Infernal Troglodyte","Dungeon",   1,  5,  4,  1,  3,   6, 5,    84),
    Creature("Harpy",             "Dungeon",    2,  6,  5,  1,  4,  14, 6,   154, flying=True),
    Creature("Harpy Hag",         "Dungeon",    2,  8,  6,  1,  4,  14, 9,   238, flying=True, no_retaliation=True),
    Creature("Beholder",          "Dungeon",    3,  9,  7,  3,  5,  22, 5,   336, shots=12),
    Creature("Evil Eye",          "Dungeon",    3, 10,  8,  3,  5,  22, 7,   367, shots=24),
    Creature("Medusa",            "Dungeon",    4,  9,  9,  6,  8,  25, 5,   517, shots=4),
    Creature("Medusa Queen",      "Dungeon",    4, 10, 10,  6,  8,  30, 6,   577, shots=8),
    Creature("Minotaur",          "Dungeon",    5, 14, 12, 12, 20,  50, 6,   835),
    Creature("Minotaur King",     "Dungeon",    5, 15, 15, 12, 20,  50, 8,  1068),
    Creature("Manticore",         "Dungeon",    6, 15, 13, 14, 20,  80, 7,  1547, flying=True),
    Creature("Scorpicore",        "Dungeon",    6, 16, 14, 14, 20,  80, 11, 1589, flying=True),
    Creature("Red Dragon",        "Dungeon",    7, 19, 19, 40, 50, 180, 11, 4702, flying=True),
    Creature("Black Dragon",      "Dungeon",    7, 25, 25, 40, 50, 300, 15, 8721, flying=True),

    # ===== STRONGHOLD (config/creatures/stronghold.json) =====
    Creature("Goblin",            "Stronghold", 1,  4,  2,  1,  2,   5, 5,    60),
    Creature("Hobgoblin",         "Stronghold", 1,  5,  3,  1,  2,   5, 7,    78),
    Creature("Wolf Rider",        "Stronghold", 2,  7,  5,  2,  4,  10, 6,   130),
    Creature("Wolf Raider",       "Stronghold", 2,  8,  5,  3,  4,  10, 8,   203, double_strike=True),
    Creature("Orc",               "Stronghold", 3,  8,  4,  2,  5,  15, 4,   192, shots=12),
    Creature("Orc Chieftain",     "Stronghold", 3,  8,  4,  2,  5,  20, 5,   240, shots=24),
    Creature("Ogre",              "Stronghold", 4, 13,  7,  6, 12,  40, 4,   416),
    Creature("Ogre Mage",         "Stronghold", 4, 13,  7,  6, 12,  60, 5,   672),
    Creature("Roc",               "Stronghold", 5, 13, 11, 11, 15,  60, 7,  1027, flying=True),
    Creature("Thunderbird",       "Stronghold", 5, 13, 11, 11, 15,  60, 11, 1106, flying=True),
    Creature("Cyclops",           "Stronghold", 6, 15, 12, 16, 20,  70, 6,  1266, shots=16),
    Creature("Cyclops King",      "Stronghold", 6, 17, 13, 16, 20,  70, 8,  1443, shots=24),
    Creature("Behemoth",          "Stronghold", 7, 17, 17, 30, 50, 160, 6,  3162),
    Creature("Ancient Behemoth",  "Stronghold", 7, 19, 19, 30, 50, 300, 9,  6168),

    # ===== FORTRESS (config/creatures/fortress.json) =====
    Creature("Gnoll",             "Fortress",   1,  3,  5,  2,  3,   6, 4,    56),
    Creature("Gnoll Marauder",    "Fortress",   1,  4,  6,  2,  3,   6, 5,    90),
    Creature("Lizardman",         "Fortress",   2,  5,  6,  1,  3,  14, 4,   126, shots=12),
    Creature("Lizard Warrior",    "Fortress",   2,  6,  8,  2,  5,  14, 5,   156, shots=24),
    Creature("Serpent Fly",       "Fortress",   3,  7,  9,  2,  5,  20, 9,   268, flying=True),
    Creature("Dragon Fly",        "Fortress",   3,  8, 10,  2,  5,  20, 13,  312, flying=True),
    Creature("Basilisk",          "Fortress",   4, 11, 11,  6, 10,  35, 5,   552),
    Creature("Greater Basilisk",  "Fortress",   4, 12, 12,  6, 10,  40, 7,   714),
    Creature("Gorgon",            "Fortress",   5, 10, 14, 12, 16,  70, 5,   890),
    Creature("Mighty Gorgon",     "Fortress",   5, 11, 16, 12, 16,  70, 6,  1028),
    Creature("Wyvern",            "Fortress",   6, 14, 14, 14, 18,  70, 7,  1350, flying=True),
    Creature("Wyvern Monarch",    "Fortress",   6, 14, 14, 18, 22,  70, 11, 1518, flying=True),
    Creature("Hydra",             "Fortress",   7, 16, 18, 25, 45, 175, 5,  4120, no_retaliation=True),
    Creature("Chaos Hydra",       "Fortress",   7, 18, 20, 25, 45, 250, 7,  5931, no_retaliation=True),

    # ===== CONFLUX (config/creatures/conflux.json) =====
    Creature("Pixie",             "Conflux",    1,  2,  2,  1,  2,   3, 7,    55, flying=True),
    Creature("Sprite",            "Conflux",    1,  2,  2,  1,  3,   3, 9,    95, flying=True, no_retaliation=True),
    Creature("Air Elemental",     "Conflux",    2,  9,  9,  2,  8,  25, 7,   356),
    Creature("Earth Elemental",   "Conflux",    2, 10, 10,  4,  8,  40, 4,   330),
    Creature("Fire Elemental",    "Conflux",    2, 10,  8,  4,  6,  35, 6,   345),
    Creature("Water Elemental",   "Conflux",    2,  8, 10,  3,  7,  30, 5,   315),
    Creature("Storm Elemental",   "Conflux",    3,  9,  9,  2,  8,  25, 8,   486, shots=24),
    Creature("Ice Elemental",     "Conflux",    3,  8, 10,  3,  7,  30, 6,   380, shots=24),
    Creature("Magma Elemental",   "Conflux",    4, 11, 11,  6, 10,  40, 6,   490),
    Creature("Energy Elemental",  "Conflux",    4, 12,  8,  4,  6,  35, 8,   470, flying=True),
    Creature("Gold Golem",        "Conflux",    5, 11, 12,  8, 10,  50, 5,   600),
    Creature("Diamond Golem",     "Conflux",    5, 13, 12, 10, 14,  60, 5,   775),
    Creature("Psychic Elemental", "Conflux",    6, 15, 13, 10, 20,  75, 7,  1669),
    Creature("Magic Elemental",   "Conflux",    6, 15, 13, 15, 25,  80, 9,  2012),
    Creature("Firebird",          "Conflux",    7, 18, 18, 30, 40, 150, 15, 4547, flying=True),
    Creature("Phoenix",           "Conflux",    7, 21, 18, 30, 40, 200, 21, 6721, flying=True),

    # ===== NEUTRAL (config/creatures/neutral.json) =====
    Creature("Peasant",           "Neutral",    1,  1,  1,  1,  1,   1, 3,    15),
    Creature("Halfling",          "Neutral",    1,  4,  2,  1,  3,   4, 5,    75, shots=24),
    Creature("Boar",              "Neutral",    2,  6,  6,  2,  3,  15, 6,   145),
    Creature("Rogue",             "Neutral",    2,  8,  1,  2,  4,  10, 6,   135, no_retaliation=True),
    Creature("Mummy",             "Neutral",    3,  7,  7,  3,  5,  30, 5,   270),
    Creature("Nomad",             "Neutral",    3,  9,  8,  2,  6,  30, 7,   345),
    Creature("Troll",             "Neutral",    5, 14,  7, 10, 15,  40, 7,  1024),
    Creature("Sharpshooter",      "Neutral",    4, 12, 10,  8, 10,  15, 9,   585, shots=32),
    Creature("Enchanter",         "Neutral",    6, 17, 12, 14, 14,  30, 9,  1210, shots=24),
    Creature("Faerie Dragon",     "Neutral",    7, 20, 20, 20, 30, 500, 15,19580, flying=True),
    Creature("Rust Dragon",       "Neutral",    7, 30, 30, 50, 70, 750, 17,26433, flying=True),
    Creature("Crystal Dragon",    "Neutral",    7, 40, 40, 60, 75, 800, 16,39338, flying=True),
    Creature("Azure Dragon",      "Neutral",    7, 50, 50, 70, 80,1000, 19,78845, flying=True),
]

# Budujemy indeks do szybkiego wyszukiwania
_CREATURE_INDEX = {}
for _c in CREATURES:
    key = _c.name.lower()
    _CREATURE_INDEX[key] = _c
    # aliasy bez spacji/myślników
    _CREATURE_INDEX[key.replace(" ", "")] = _c
    _CREATURE_INDEX[key.replace(" ", "_")] = _c
    _CREATURE_INDEX[key.replace(" ", "-")] = _c


def find_creature(query: str) -> Creature:
    """Wyszukuje stworzenie po nazwie (case-insensitive, fuzzy match)."""
    q = query.strip().lower()

    # 1. Dokładne dopasowanie
    if q in _CREATURE_INDEX:
        return _CREATURE_INDEX[q]

    # 2. Dopasowanie bez spacji/myślników
    q_clean = q.replace(" ", "").replace("-", "").replace("_", "")
    for key, c in _CREATURE_INDEX.items():
        if key.replace(" ", "").replace("-", "").replace("_", "") == q_clean:
            return c

    # 3. Prefix match
    matches = [c for key, c in _CREATURE_INDEX.items() if key.startswith(q)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # Wybierz unikalne (deduplikacja bo aliasy)
        unique = list({c.name: c for c in matches}.values())
        if len(unique) == 1:
            return unique[0]
        names = ", ".join(c.name for c in unique[:5])
        print(f"  Niejednoznaczne: '{query}' pasuje do: {names}", file=sys.stderr)
        sys.exit(1)

    # 4. Substring match
    matches = [c for key, c in _CREATURE_INDEX.items() if q in key]
    unique = list({c.name: c for c in matches}.values())
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        names = ", ".join(c.name for c in unique[:5])
        print(f"  Niejednoznaczne: '{query}' pasuje do: {names}", file=sys.stderr)
        sys.exit(1)

    print(f"  Nie znaleziono stworzenia: '{query}'", file=sys.stderr)
    print(f"  Użyj --list żeby zobaczyć dostępne stworzenia.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Parsowanie opisu armii: "10 pikeman, 2 griffin" lub "lot of boar"
# ---------------------------------------------------------------------------
def parse_army(text: str) -> List[Tuple[Creature, int, Optional[Tuple[int, int]]]]:
    """
    Parsuje opis armii. Zwraca listę (Creature, count, range_or_None).
    count = -1 gdy podano deskryptor ilościowy (range jest ustawiony).
    """
    stacks = []
    parts = re.split(r',\s*', text.strip())

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Próba: "lot of boar", "horde of skeleton", "few archangel"
        qty_match = re.match(
            r'(few|several|pack|lots?|horde|throng|swarm|zounds|legion)\s+(?:of\s+)?(.+)',
            part, re.IGNORECASE
        )
        if qty_match:
            descriptor = qty_match.group(1).lower()
            if descriptor == "lot":
                descriptor = "lots"
            creature_name = qty_match.group(2).strip()
            creature = find_creature(creature_name)
            lo, hi = QUANTITY_DESCRIPTORS[descriptor]
            mid = (lo + hi) // 2
            stacks.append((creature, mid, (lo, hi)))
            continue

        # Próba: "35 boar", "10 pikeman"
        num_match = re.match(r'(\d+)\s+(.+)', part)
        if num_match:
            count = int(num_match.group(1))
            creature_name = num_match.group(2).strip()
            creature = find_creature(creature_name)
            stacks.append((creature, count, None))
            continue

        print(f"  Nie rozumiem: '{part}'", file=sys.stderr)
        print(f"  Format: '10 pikeman' lub 'lot of boar'", file=sys.stderr)
        sys.exit(1)

    return stacks


# ---------------------------------------------------------------------------
# Stack — stos stworzeń w walce (odpowiednik CStack w VCMI)
# ---------------------------------------------------------------------------
@dataclass
class Stack:
    creature: Creature
    count: int
    first_hp: int = 0
    retaliations_left: int = 0
    shots_left: int = 0
    has_acted: bool = False
    side: int = 0

    def __post_init__(self):
        self.first_hp = self.creature.hit_points
        self.retaliations_left = self.creature.retaliations
        self.shots_left = self.creature.shots

    @property
    def alive(self) -> bool:
        return self.count > 0

    @property
    def total_hp(self) -> int:
        if self.count <= 0:
            return 0
        return (self.count - 1) * self.creature.hit_points + self.first_hp

    @property
    def army_value(self) -> int:
        return self.creature.ai_value * self.count

    def reset_turn(self):
        self.retaliations_left = self.creature.retaliations
        self.has_acted = False


# ---------------------------------------------------------------------------
# Formuła obrażeń z DamageCalculator.cpp (linie 556-593)
# ---------------------------------------------------------------------------
def calc_damage_factor(att: int, dfn: int) -> float:
    diff = att - dfn
    if diff > 0:
        return 1.0 + min(ATTACK_POINT_DAMAGE_FACTOR * diff,
                         ATTACK_POINT_DAMAGE_FACTOR_CAP)
    elif diff < 0:
        return 1.0 - min(DEFENSE_POINT_DAMAGE_FACTOR * abs(diff),
                         DEFENSE_POINT_DAMAGE_FACTOR_CAP)
    return 1.0


def calc_damage(attacker: Stack, defender: Stack, shooting: bool = False) -> int:
    base_dmg = random.randint(attacker.creature.min_damage,
                              attacker.creature.max_damage)
    stack_dmg = base_dmg * attacker.count
    factor = calc_damage_factor(attacker.creature.attack,
                                defender.creature.defense)

    # Kara 50% za strzał w zwarciu (DamageCalculator.cpp:386-389)
    if attacker.creature.shooter and not shooting:
        factor *= 0.5

    return max(1, math.floor(stack_dmg * factor))


def apply_damage(target: Stack, damage: int) -> int:
    if not target.alive:
        return 0
    kills = 0
    target.first_hp -= damage
    while target.first_hp <= 0 and target.count > 0:
        kills += 1
        target.count -= 1
        if target.count > 0:
            target.first_hp += target.creature.hit_points
    if target.count <= 0:
        target.count = 0
        target.first_hp = 0
    return kills


# ---------------------------------------------------------------------------
# Symulacja jednej bitwy
# ---------------------------------------------------------------------------
def simulate_battle(player_stacks: List[Stack], enemy_stacks: List[Stack],
                    verbose: bool = False) -> bool:
    all_stacks = player_stacks + enemy_stacks
    max_turns = 100

    for turn in range(1, max_turns + 1):
        for s in all_stacks:
            s.reset_turn()

        alive_stacks = [s for s in all_stacks if s.alive]
        alive_stacks.sort(key=lambda s: (-s.creature.speed, s.side))

        if verbose and turn <= 3:
            print(f"\n--- Tura {turn} ---")
            for s in alive_stacks:
                tag = "gracz" if s.side == 0 else "wrog"
                print(f"  {s.creature.name} x{s.count} "
                      f"(HP: {s.total_hp}, {tag})")

        for active in alive_stacks:
            if not active.alive or active.has_acted:
                continue
            active.has_acted = True

            enemies = [s for s in all_stacks
                       if s.alive and s.side != active.side]
            if not enemies:
                break

            # Strategia wyboru celu:
            # - Strzelcy atakują cel z najniższym łącznym HP (eliminacja)
            # - Melee atakuje cel z najmniejszą liczbą (eliminacja stosów)
            target = min(enemies, key=lambda s: s.total_hp)

            # Decyzja: strzał czy melee
            can_shoot = (active.creature.shooter and active.shots_left > 0)
            shooting = can_shoot  # uproszczenie: strzelec zawsze strzela

            # --- Atak ---
            dmg = calc_damage(active, target, shooting)
            kills = apply_damage(target, dmg)
            if shooting:
                active.shots_left -= 1

            if verbose and turn <= 3:
                mode = ">>>" if shooting else ">>"
                print(f"  {mode} {active.creature.name} x{active.count} -> "
                      f"{target.creature.name}: {dmg} dmg, {kills} kills "
                      f"(zostalo: {target.count})")

            # --- Double strike (Crusader, Dread Knight, etc.) ---
            if active.creature.double_strike and target.alive:
                dmg2 = calc_damage(active, target, shooting)
                kills2 = apply_damage(target, dmg2)
                if verbose and turn <= 3:
                    print(f"      (double) +{dmg2} dmg, +{kills2} kills "
                          f"(zostalo: {target.count})")

            # --- Kontratak ---
            if (target.alive
                    and target.retaliations_left > 0
                    and not shooting
                    and not active.creature.no_retaliation):
                target.retaliations_left -= 1
                ret_dmg = calc_damage(target, active, shooting=False)
                ret_kills = apply_damage(active, ret_dmg)
                if verbose and turn <= 3:
                    print(f"     << kontra {target.creature.name}: "
                          f"{ret_dmg} dmg, {ret_kills} kills "
                          f"(zostalo: {active.count})")

        player_alive = any(s.alive for s in player_stacks)
        enemy_alive = any(s.alive for s in enemy_stacks)

        if not enemy_alive:
            if verbose:
                print(f"\n==> WYGRANA GRACZA w turze {turn}!")
                for s in player_stacks:
                    if s.alive:
                        print(f"    Przezylo: {s.creature.name} x{s.count} "
                              f"(HP: {s.total_hp})")
            return True
        if not player_alive:
            if verbose:
                print(f"\n==> PRZEGRANA w turze {turn}.")
            return False

    return False


# ---------------------------------------------------------------------------
# Silnik symulacji
# ---------------------------------------------------------------------------
def run_simulations(player_army: List[Tuple[Creature, int]],
                    enemy_army: List[Tuple[Creature, int]],
                    n_sims: int, verbose_first: bool = False) -> float:
    wins = 0
    for i in range(n_sims):
        p_stacks = [Stack(creature=c, count=n, side=0) for c, n in player_army]
        e_stacks = [Stack(creature=c, count=n, side=1) for c, n in enemy_army]
        if simulate_battle(p_stacks, e_stacks, verbose=(verbose_first and i == 0)):
            wins += 1
    return wins / n_sims * 100


# ---------------------------------------------------------------------------
# Wyświetlanie
# ---------------------------------------------------------------------------
def print_army(label: str, army: List[Tuple[Creature, int]]):
    parts = [f"{n}x {c.name}" for c, n in army]
    print(f"  {label}: {', '.join(parts)}")


def ai_value_total(army: List[Tuple[Creature, int]]) -> int:
    return sum(c.ai_value * n for c, n in army)


def hp_total(army: List[Tuple[Creature, int]]) -> int:
    return sum(c.hit_points * n for c, n in army)


def print_static_analysis(player: List[Tuple[Creature, int]],
                           enemy: List[Tuple[Creature, int]]):
    p_val = ai_value_total(player)
    e_val = ai_value_total(enemy)
    ratio = p_val / e_val if e_val > 0 else float('inf')

    print(f"\n  AIValue gracza:  {p_val:>8}")
    print(f"  AIValue wroga:   {e_val:>8}")
    print(f"  Stosunek:        {ratio:>8.2f}x "
          f"({'przewaga gracza' if ratio > 1 else 'PRZEWAGA WROGA'})")
    print(f"  HP gracza:       {hp_total(player):>8}")
    print(f"  HP wroga:        {hp_total(enemy):>8}")


def list_creatures(faction_filter: Optional[str] = None):
    factions = {}
    for c in CREATURES:
        factions.setdefault(c.faction, []).append(c)

    for faction, creatures in factions.items():
        if faction_filter and faction_filter.lower() not in faction.lower():
            continue
        print(f"\n  === {faction.upper()} ===")
        print(f"  {'Nazwa':<22} {'Lv':>2} {'Att':>3} {'Def':>3} "
              f"{'Dmg':>7} {'HP':>4} {'Spd':>3} {'AIVal':>6}  Cechy")
        print(f"  {'─'*22} {'─'*2} {'─'*3} {'─'*3} "
              f"{'─'*7} {'─'*4} {'─'*3} {'─'*6}  {'─'*20}")
        for c in creatures:
            traits = []
            if c.shooter:
                traits.append(f"strzelec({c.shots})")
            if c.flying:
                traits.append("latajacy")
            if c.no_retaliation:
                traits.append("bez-kontr")
            if c.double_strike:
                traits.append("2x-atak")
            if c.retaliations > 1:
                r = "inf" if c.retaliations >= 99 else str(c.retaliations)
                traits.append(f"kontr={r}")
            trait_str = ", ".join(traits) if traits else ""
            print(f"  {c.name:<22} {c.level:>2} {c.attack:>3} {c.defense:>3} "
                  f"{c.min_damage:>3}-{c.max_damage:<3} {c.hit_points:>4} "
                  f"{c.speed:>3} {c.ai_value:>6}  {trait_str}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="VCMI Battle Estimator — Monte Carlo na bazie "
                    "DamageCalculator.cpp",
        usage='%(prog)s "10 pikeman, 2 griffin" vs "lot of boar" [-n 2000] [-v]'
    )
    parser.add_argument("army_specs", nargs="*",
                        help='Armie rozdzielone słowem "vs"')
    parser.add_argument("--list", nargs="?", const="", default=None,
                        help="Wyświetl listę stworzeń (opcjonalnie: nazwa frakcji)")
    parser.add_argument("--simulations", "-n", type=int, default=2000,
                        help="Liczba symulacji (domyślnie: 2000)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Pokaż szczegóły pierwszej symulacji")
    args = parser.parse_args()

    if args.list is not None:
        faction = args.list if args.list else None
        list_creatures(faction)
        return

    # Parsowanie "A vs B" z argumentów CLI
    full_text = " ".join(args.army_specs)
    # Rozdziel po "vs" (case insensitive)
    vs_parts = re.split(r'\s+vs\.?\s+', full_text, flags=re.IGNORECASE)
    if len(vs_parts) != 2:
        parser.print_help()
        print("\nPrzyklad:")
        print('  python3 tools/battle_estimator.py '
              '"10 pikeman, 2 griffin" vs "lot of boar"')
        print('  python3 tools/battle_estimator.py '
              '"5 archangel" vs "horde of black dragon"')
        print('  python3 tools/battle_estimator.py --list')
        sys.exit(1)

    player_parsed = parse_army(vs_parts[0])
    enemy_parsed = parse_army(vs_parts[1])

    # Sprawdź czy któraś strona ma zakresy (deskryptory ilościowe)
    has_ranges = any(r is not None for _, _, r in player_parsed) or \
                 any(r is not None for _, _, r in enemy_parsed)

    print("=" * 65)
    print("  VCMI Battle Estimator")
    print("  Formula obrazen: lib/battle/DamageCalculator.cpp")
    print("  Progi ilosciowe: lib/CCreatureHandler.cpp:237-257")
    print("=" * 65)

    if not has_ranges:
        # Dokładne liczby — pojedyncza symulacja
        player_army = [(c, n) for c, n, _ in player_parsed]
        enemy_army = [(c, n) for c, n, _ in enemy_parsed]

        print_army("Gracz", player_army)
        print_army("Wrog", enemy_army)

        print(f"\n{'=' * 65}")
        print(f"  ANALIZA STATYCZNA")
        print(f"{'=' * 65}")
        print_static_analysis(player_army, enemy_army)

        print(f"\n{'=' * 65}")
        print(f"  SYMULACJA MONTE CARLO ({args.simulations} bitew)")
        print(f"{'=' * 65}")

        win_pct = run_simulations(player_army, enemy_army,
                                  args.simulations,
                                  verbose_first=args.verbose)
        print(f"\n  Szansa wygranej: {win_pct:.1f}%")
        _print_verdict(win_pct)

    else:
        # Zakresy — skanowanie
        # Zbieramy informacje o zakresach
        range_stacks = []
        for parsed in [player_parsed, enemy_parsed]:
            for c, mid, rng in parsed:
                if rng:
                    range_stacks.append((c, rng))

        # Dla uproszczenia: jeśli jest 1 zakres, skanujemy go
        # Jeśli więcej — bierzemy środkowe wartości dla wszystkich
        # oprócz pierwszego wroga z zakresem
        if len(range_stacks) == 1:
            range_creature, (lo, hi) = range_stacks[0]

            # Buduj armie z mid-wartościami (te bez zakresu mają count)
            player_army = [(c, n) for c, n, _ in player_parsed if _ is None]
            for c, n, r in player_parsed:
                if r:
                    player_army.append((c, (r[0] + r[1]) // 2))
            enemy_army = [(c, n) for c, n, _ in enemy_parsed if _ is None]
            for c, n, r in enemy_parsed:
                if r:
                    enemy_army.append((c, (r[0] + r[1]) // 2))

            print_army("Gracz", [(c, n) for c, n, _ in player_parsed])
            desc = [d for d, (l, h) in QUANTITY_DESCRIPTORS.items()
                    if l == lo][0].upper() if any(
                l == lo for _, (l, _) in QUANTITY_DESCRIPTORS.items()) else "?"
            print(f"  Wrog:  {desc} ({lo}-{hi}) {range_creature.name}")

            print(f"\n{'=' * 65}")
            print(f"  ANALIZA STATYCZNA (dla srodka zakresu)")
            print(f"{'=' * 65}")
            print_static_analysis(player_army, enemy_army)

            print(f"\n{'=' * 65}")
            print(f"  SKANOWANIE ZAKRESU {lo}-{hi} "
                  f"({args.simulations} bitew/punkt)")
            print(f"{'=' * 65}")
            print(f"\n  {'Ilosc':>6} │ {'Win %':>7} │ Wykres")
            print(f"  {'─'*6}─┼─{'─'*7}─┼─{'─'*40}")

            # step — przynajmniej 15 punktów, max co 1
            step = max(1, (hi - lo) // 30)
            scan_points = list(range(lo, hi + 1, step))
            if scan_points[-1] != hi:
                scan_points.append(hi)

            results = []
            for count in scan_points:
                # Buduj armie z tym count
                p_army = [(c, n) for c, n, _ in player_parsed]
                e_army = [(c, n) for c, n, _ in enemy_parsed]
                # Zastąp zakresy dokładną wartością
                p_army_fixed = []
                for c, n, r in player_parsed:
                    p_army_fixed.append((c, count if r else n))
                e_army_fixed = []
                for c, n, r in enemy_parsed:
                    e_army_fixed.append((c, count if r else n))

                win_pct = run_simulations(
                    p_army_fixed, e_army_fixed,
                    args.simulations,
                    verbose_first=(args.verbose and count == lo)
                )
                results.append(win_pct)
                bar = "█" * int(win_pct / 2.5)
                print(f"  {count:>6} │ {win_pct:>6.1f}% │ {bar}")

            avg_win = sum(results) / len(results) if results else 0
            print(f"\n  Srednia szansa w zakresie: {avg_win:.1f}%")
            _print_verdict(avg_win)
        else:
            # Wiele zakresów — bierzemy środki
            player_army = []
            for c, n, r in player_parsed:
                player_army.append((c, n))
            enemy_army = []
            for c, n, r in enemy_parsed:
                enemy_army.append((c, n))

            print_army("Gracz", player_army)
            print_army("Wrog", enemy_army)
            print("  (Deskryptory ilosciowe zamienione na wartosci srodkowe)")

            print(f"\n{'=' * 65}")
            print(f"  ANALIZA STATYCZNA")
            print(f"{'=' * 65}")
            print_static_analysis(player_army, enemy_army)

            print(f"\n{'=' * 65}")
            print(f"  SYMULACJA MONTE CARLO ({args.simulations} bitew)")
            print(f"{'=' * 65}")
            win_pct = run_simulations(player_army, enemy_army,
                                      args.simulations,
                                      verbose_first=args.verbose)
            print(f"\n  Szansa wygranej: {win_pct:.1f}%")
            _print_verdict(win_pct)

    print()


def _print_verdict(win_pct: float):
    print(f"\n{'=' * 65}")
    print("  WERDYKT")
    print(f"{'=' * 65}")
    if win_pct < 10:
        print(f"  ZDECYDOWANIE NIE ATAKUJ")
        print(f"  Armia jest za slaba. Potrzebujesz znacznie wiecej jednostek.")
    elif win_pct < 30:
        print(f"  RACZEJ NIE ATAKUJ")
        print(f"  Masz male szanse ({win_pct:.0f}%), "
              f"ryzyko utraty armii jest wysokie.")
    elif win_pct < 50:
        print(f"  RYZYKOWNE")
        print(f"  Mozesz wygrac ({win_pct:.0f}%), "
              f"ale prawdopodobnie stracisz wiekszosc armii.")
    elif win_pct < 70:
        print(f"  MOZNA SPROBOWAC")
        print(f"  Szanse sa umiarkowane ({win_pct:.0f}%), straty beda znaczne.")
    elif win_pct < 90:
        print(f"  TAK, ATAKUJ")
        print(f"  Powinienes wygrac ({win_pct:.0f}%), "
              f"ale licz sie ze stratami.")
    else:
        print(f"  PEWNA WYGRANA")
        print(f"  Zdecydowana przewaga ({win_pct:.0f}%). Atakuj smialo!")


if __name__ == "__main__":
    main()
