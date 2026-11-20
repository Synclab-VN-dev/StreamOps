"""Resolve focused Talisman tooltips from ordered NVDA and Steam Input events."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..runtime.events.model import EventEnvelope
from .equipment.parser import FAVORITE, normalize

ITEM_TYPE = re.compile(r"(?:Ancestral )?(?:(?:Set|Unique) Charm|Legendary Horadric Seal)")
POWER = re.compile(r"(\d+) Item Power")
SET_TIER = re.compile(r"(?<!\w)\((\d+)\)\s+Set:\s*\.?\s*", re.IGNORECASE)
MAX_LINES = 128


def title(line: str) -> str | None:
    name = line.removeprefix(FAVORITE)
    if name.isupper() and name != "EQUIPPED":
        return name
    return None


@dataclass
class TalismanTooltip:
    session: str = ""
    # Only unresolved tooltip speech is checkpointed. Keep its original sequence.
    lines: list[tuple[int, str]] = field(default_factory=list)

    def consume(self, event: EventEnvelope) -> dict | None:
        if event.session_id != self.session:
            self.session = event.session_id
            self.lines.clear()
        if event.type == "input.marker.raw":
            if event.data.get("state") == "down":
                self.lines.clear()
            return None
        if event.type != "speech.raw":
            return None
        text = normalize(str(event.data.get("text") or ""))
        if text in {"Charm", "Seal"}:
            self.lines = [(event.event_seq, text)]
            return None
        if text == "EQUIPPED":
            if not self.lines or self.lines[-1][1] not in {"Charm", "Seal"}:
                self.lines.clear()
        elif not self.lines:
            if not text.startswith(FAVORITE):
                return None
        if len(self.lines) >= MAX_LINES or len(text) > 4096:
            self.lines.clear()
            return None
        self.lines.append((event.event_seq, text))
        if text in {"Unequip", "Drop"}:
            observation = self.resolve()
            self.lines.clear()
            return observation
        return None

    def resolve(self) -> dict | None:
        lines = [text for _, text in self.lines]
        if "Bottom action button" not in lines:
            return None
        actions = lines.index("Bottom action button")
        if lines[actions:actions + 2] != ["Bottom action button", "Move"]:
            return None
        # A comparison may speak two headers, sometimes truncating the first.
        # The last complete name/type/power header owns the focused tooltip.
        names = [i for i in range(actions) if title(lines[i]) and (
            lines[i].startswith(FAVORITE) or (i + 1 < actions and ITEM_TYPE.fullmatch(lines[i + 1]))
        )]
        if not names:
            return None
        start = names[-1]
        if start + 2 >= actions or not ITEM_TYPE.fullmatch(lines[start + 1]):
            return None
        power = POWER.fullmatch(lines[start + 2])
        if not power:
            return None
        kind = "charm" if lines[start + 1].endswith("Charm") else "seal"
        if lines[-1] == "Unequip":
            if lines[:2] != [kind.capitalize(), "EQUIPPED"] or len(names) != 1:
                return None
            role = "equipped"
        else:
            role = "bag"

        details = lines[start + 3:actions]
        # Keep comparison deductions and set membership out of item attributes.
        own = []
        for line in details:
            if line.startswith(("Properties lost when equipped", "Requires Level", "Sell Value:")):
                break
            if line not in {"blank", "Armory Loadout"}:
                own.append(line)
        attributes = []
        bonuses = []
        for line in own:
            tiers = list(SET_TIER.finditer(line))
            if tiers:
                for index, tier in enumerate(tiers):
                    end = tiers[index + 1].start() if index + 1 < len(tiers) else len(line)
                    description = line[tier.end():end].strip()
                    if description.endswith(".."):
                        description = description[:-1]
                    if description:
                        bonuses.append(f"({tier[1]}) Set: {description}")
            elif re.search(r"\d", line):
                attributes.append(line)
        return {
            "start": self.lines[start][0], "end": self.lines[-1][0],
            "kind": kind, "role": role, "name": title(lines[start]),
            "type": lines[start + 1], "power": int(power[1]), "attributes": attributes, "set_bonuses": bonuses,
            "comparison": title(lines[names[-2]]) if role == "bag" and len(names) == 2 else None,
        }
