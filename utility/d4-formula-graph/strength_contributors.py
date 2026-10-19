"""Bounded Rogue Strength candidate contributors. No Golden imports or reads.

The active UI has eight gate endpoints for four board connections.
Each connection provides only ONE +5 primary-stat bonus, not two.
A glyph socket tooltip's '+N Strength' is an aggregate of purchased
nodes in range; it is NOT an additional standalone source.

Class base/level scaling is research-grade pending exact 3.2.1 validation.
This module intentionally DOES NOT model unknown altars or item affix NIDs.
"""
from __future__ import annotations
from typing import Mapping
import re

from contributor_contract import SourceContribution
import graph

STRENGTH_ID = "maxroll.heroDetails.108"
FLAT = re.compile(r"^\+(\d+(?:\.\d+)?) Strength$")


def validate_rules(rules: Mapping) -> None:
    graph.reject(
        type(rules) is dict and
        set(rules) == {"schema", "classId", "patch", "levelOneBaseStrength",
                       "perAdditionalLevelStrength", "gateBonusStrength",
                       "provenance", "verification"},
        "INVALID_STRENGTH_RULE_FIELDS",
    )
    graph.reject(
        rules["schema"] == "strength-contribution-research-v1"
        and rules["classId"] == "rogue"
        and rules["patch"] == "3.2.1.73552"
        and type(rules["levelOneBaseStrength"]) is int
        and rules["levelOneBaseStrength"] == 7
        and type(rules["perAdditionalLevelStrength"]) is int
        and rules["perAdditionalLevelStrength"] == 1
        and type(rules["gateBonusStrength"]) is int
        and rules["gateBonusStrength"] == 5
        and rules["verification"] ==
        "RESEARCH_CANDIDATE_NOT_CAUSALLY_VERIFIED_ON_3_2_1"
        and type(rules["provenance"]) is dict
        and set(rules["provenance"]) == {"classStats", "levelGrowth", "gatePairs"}
        and all(type(url) is str and url.startswith("https://")
                for url in rules["provenance"].values()),
        "UNPROVEN_OR_CHANGED_STRENGTH_MECHANICS",
    )
    graph.reject(
        not any("golden" in str(k).lower() or "expected" in str(k).lower()
                for k in rules),
        "GOLDEN_VALUES_FORBIDDEN_IN_RULE_INPUT",
    )


def paragon_strength(paragon: dict, rules: dict):
    nodes = paragon["sourceActiveNodes"]
    boards = set()
    non_socket_flat = 0.0
    rendered_gate_sum = 0.0
    gate_count = 0
    socket_summary_sum = 0.0
    socket_count = 0
    contributing_node_ids = []
    for node in nodes:
        boards.add(node["boardIndex"])
        classes = node["className"].split()
        is_gate = "d4t-gate" in classes
        is_socket = "d4t-socket" in classes
        lines = (node["tooltip"] or "").splitlines()
        strength = sum(float(match.group(1)) for line in lines
                       if (match := FLAT.fullmatch(line.strip())) is not None)
        if is_gate:
            graph.reject(strength == rules["gateBonusStrength"],
                         "GATE_STRENGTH_TOOLTIP_MISMATCH")
            gate_count += 1
            rendered_gate_sum += strength
        elif is_socket:
            socket_count += 1
            socket_summary_sum += strength
        else:
            non_socket_flat += strength
            if strength:
                contributing_node_ids.append(node["index"])
    # This bounded test explicitly rejects a topology different from the
    # observed five boards. It does not infer a purchased gate via a UI class.
    graph.reject(boards == {0, 1, 2, 3, 4} and socket_count == 5,
                 "UNSUPPORTED_PARAGON_BOARD_OR_SOCKET_TOPOLOGY")
    connections = len(boards) - 1
    graph.reject(gate_count == 2 * connections,
                 "GATE_PAIRS_CANNOT_BE_ESTABLISHED")
    credited = connections * rules["gateBonusStrength"]
    effective = non_socket_flat + credited
    graph.reject(effective >= 0, "INVALID_EFFECTIVE_PARAGON_STRENGTH")
    return {
        "effectiveFlatSubtotal": effective,
        "nonSocketNodeFlatSubtotal": non_socket_flat,
        "nonSocketNodeIndices": contributing_node_ids,
        "observedGateEndpoints": gate_count,
        "creditedGateConnections": connections,
        "displayedGateEndpointSubtotalExcludedAsDuplicate": rendered_gate_sum - credited,
        "observedGlyphSocketStrengthSummariesExcluded": socket_summary_sum,
        "reason": "GATE_PAIR_COUNTS_ONCE_GLYPH_SOCKET_SUMMARIZES_EXISTING_NODES",
        "sourceEvidence": rules["provenance"]["gatePairs"],
        "candidateCompleteness": "PARAGON_TOOLTIP_RECONCILED_CAUSAL_GAME_PATCH_UNVERIFIED",
    }


class RogueStrengthBaseLevel:
    family = "ROGUE_STRENGTH_BASE_AND_LEVEL"
    def __init__(self, rules: dict):
        validate_rules(rules)
        self._rules = rules

    def produce(self, source, paragon, rolls):
        graph.reject(source["fixture"]["class"] == "Rogue" and
                     source["fixture"]["gameVersion"] == self._rules["patch"],
                     "STRENGTH_BASE_CLASS_PATCH_MISMATCH")
        level = source["currentReadOnlyPublicProfile"]["level"]
        graph.reject(type(level) is int and 1 <= level <= 100,
                     "INVALID_ROGUE_STRENGTH_LEVEL")
        value = self._rules["levelOneBaseStrength"] + (
            level - 1) * self._rules["perAdditionalLevelStrength"]
        return (SourceContribution(
            STRENGTH_ID, self.family, value,
            "class/rogue/level/%d" % level,
            "COMMUNITY_RESEARCH_BASE_AND_LEVEL_NOT_CAUSAL_ON_3_2_1"),)


class EffectiveParagonStrength:
    family = "PARAGON_EFFECTIVE_STRENGTH"
    def __init__(self, rules: dict):
        validate_rules(rules)
        self._rules = rules

    def produce(self, source, paragon, rolls):
        audited = paragon_strength(paragon, self._rules)
        return (SourceContribution(
            STRENGTH_ID, self.family, audited["effectiveFlatSubtotal"],
            "paragon/reconciled-active-nodes-and-board-gate-pairs",
            "CAPTURED_ACTIVE_UI_RECONCILED_GATES_AND_SOCKET_SUMMARIES"),)
