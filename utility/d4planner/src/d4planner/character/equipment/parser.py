from __future__ import annotations

import html
import re
from hashlib import sha256

from ..models import ParsedItem

RARITIES = {"Magic", "Rare", "Legendary", "Unique"}
TYPE_RE = re.compile(r"^(?:(Ancestral) )?(?:(Magic|Rare|Legendary|Unique) )?(.+)$")
POWER_RE = re.compile(r"^(\d[\d,]*) Item Power$")
BASE_PATTERNS = (
    ("armor", re.compile(r"^([\d,]+) Armor$")),
    ("allResist", re.compile(r"^([\d,]+) All Resist$")),
    ("damagePerSecond", re.compile(r"^([\d,]+) Damage Per Second$")),
    ("damagePerHit", re.compile(r"^\[([\d,]+) - ([\d,]+)\] Damage per Hit$")),
    ("attacksPerSecond", re.compile(r"^([\d.]+) Attacks per Second(?: \(([^)]+)\))?$")),
    ("quality", re.compile(r"^(\d+) \(\s*\+(\d+)/(\d+)\) Quality$")),
)
AFFIX_RE = re.compile(r"^(?P<op>[+x])?(?P<value>[\d,.]+)(?P<unit>%?) (?P<name>.+?)(?: \+?\[(?P<min>[\d,.]+) - (?P<max>[\d,.]+)\](?P<rangeunit>%?))?(?: \((?P<delta>[+-][\d.]+%?)\))?$")
FAVORITE = "[FAVORITED ITEM]. "
NOISE = {"blank", "Armory Loadout", "Left action button", "Right action button", "Bottom action button", "Hold", "Drop", "Mark as Junk", "Scroll Down", "Right analog stick down"}


def normalize(text: str) -> str:
    return html.unescape(text).strip()


def parse_type(line: str) -> tuple[bool, str | None, str] | None:
    line = normalize(line)
    m = TYPE_RE.match(line)
    if not m or line in NOISE or POWER_RE.match(line):
        return None
    ancestral, rarity, item_type = m.groups()
    return bool(ancestral), rarity, item_type


def is_item_anchor(name: str, type_line: str, power_line: str) -> bool:
    if not POWER_RE.match(normalize(power_line)):
        return False
    parsed = parse_type(type_line)
    if not parsed:
        return False
    item_type = parsed[2]
    known = ("Helm", "Chest Armor", "Gloves", "Pants", "Boots", "Wand", "Focus", "Ring", "Amulet", "Sword")
    return item_type in known and bool(normalize(name))


def _number(value: str):
    value = value.replace(",", "")
    return float(value) if "." in value else int(value)


def parse_item(lines: list[str]) -> ParsedItem:
    raw = list(lines)
    lines = [normalize(x) for x in lines]
    name_line, type_line, power_line = lines[:3]
    favorite = name_line.startswith(FAVORITE)
    name = name_line[len(FAVORITE):] if favorite else name_line
    ancestral, rarity, item_type = parse_type(type_line) or (False, None, type_line)
    pm = POWER_RE.match(power_line)
    if not pm:
        raise ValueError("invalid item anchor")
    item = ParsedItem(name=name, item_type=item_type, item_power=int(pm.group(1).replace(",", "")), favorite=favorite, ancestral=ancestral, rarity=rarity, raw_lines=raw)
    section: str | None = None
    for line in lines[3:]:
        if not line or line in NOISE or line in {"Equip", "Unequip", "EQUIPPED"}:
            continue
        if line == "Properties lost when equipped:":
            section = "lost"; continue
        if line == "Properties gained when equipped:":
            section = "gained"; continue
        if section:
            item.comparison[section].append(line); continue
        matched = False
        for kind, rx in BASE_PATTERNS:
            m = rx.match(line)
            if not m: continue
            vals = [_number(v) for v in m.groups() if v is not None and re.match(r"^[\d,.]+$", v)]
            stat = {"kind": kind, "value": vals[0] if vals else None, "raw": line}
            if len(vals) > 1: stat["range"] = vals[:2]
            item.base_stats.append(stat); matched = True; break
        if matched: continue
        if line.startswith("Imprinted:") or line == "Legendary Power" or line == "Empty Socket":
            item.effects_raw.append(line); continue
        if line.startswith(("Requires Level ", "Sell Value:", "Durability:", "Tempers:")):
            item.metadata_raw.append(line); continue
        m = AFFIX_RE.match(line)
        if m:
            d=m.groupdict(); affix={"operator":d["op"],"value":_number(d["value"]),"unit":d["unit"] or None,"stat":d["name"],"raw":line}
            if d["min"] is not None: affix["rollMin"]=_number(d["min"]); affix["rollMax"]=_number(d["max"])
            if d["delta"] is not None: affix["comparisonDelta"]=d["delta"]
            item.affixes.append(affix)
        elif len(line) > 20:
            item.effects_raw.append(line)
    return item


def fingerprint(slot_family: str, item: ParsedItem) -> str:
    intrinsic = "|".join([slot_family, item.name, item.item_type, str(item.item_power), repr(item.base_stats), repr(item.affixes)])
    return sha256(intrinsic.encode("utf-8")).hexdigest()
