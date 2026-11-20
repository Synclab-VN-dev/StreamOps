from d4planner.character.talisman import TalismanTooltip
from d4planner.runtime.events.model import EventEnvelope


def speech(seq, text, session="session"):
    return EventEnvelope(seq, "speech.raw", "2026-11-13", session, {"text": text})


def test_bag_focus_excludes_comparison_and_set_members():
    parser = TalismanTooltip()
    for seq, text in enumerate(["EQUIPPED", "OTHER CHARM", "Set Charm", "850 Item Power",
        "FOCUSED CHARM", "Ancestral Set Charm", "900 Item Power", "+2 Skill",
        "Properties lost when equipped:", "+9 Armor", "Example set", "Some set member",
        "Bottom action button", "Move", "Hold", "Drop"], 1):
        result = parser.consume(speech(seq, text))
    assert result == {"start": 5, "end": 16, "role": "bag", "kind": "charm",
        "name": "FOCUSED CHARM", "comparison": "OTHER CHARM", "type": "Ancestral Set Charm",
        "power": 900, "attributes": ["+2 Skill"]}


def test_missing_equipped_slot_evidence_or_session_boundary_fails_closed():
    for start, end_session in [(["EQUIPPED"], "session"), (["Seal", "EQUIPPED"], "next")]:
        parser = TalismanTooltip()
        for seq, text in enumerate(start + ["FIRST SEAL", "Legendary Horadric Seal", "850 Item Power",
            "Bottom action button", "Move"], 1):
            assert parser.consume(speech(seq, text)) is None
        assert parser.consume(speech(10, "Unequip", end_session)) is None
