"""Paragon source-only additive percentage contributor for M20.

Parse only active literal tooltip lines; skip conditional bonuses. Incomplete
percent subtotal is provisional, not final Character Stat.
"""
from __future__ import annotations
import re
from contributor_contract import SourceContribution
RULES=(
    (re.compile(r"^\+(\d+(?:\.\d+)?)% Damage to Elites$"),"maxroll.heroDetails.2"),
    (re.compile(r"^\+(\d+(?:\.\d+)?)% Damage to Crowd Controlled Enemies$"),"maxroll.heroDetails.25")
)

class ParagonPercentDamage:
    family="PARAGON_UI_PERCENT_DAMAGE"
    def produce(self,source,paragon,rolls):
        rows=[]
        for node in paragon["sourceActiveNodes"]:
            for i,line in enumerate((node["tooltip"] or "").splitlines()):
                for pattern,metric_id in RULES:
                    m=pattern.fullmatch(line.strip())
                    if m:
                        rows.append(SourceContribution(
                            metric_id,self.family,float(m.group(1))/100.0,
                            "paragon/active-node/%d/line/%d"%(node["index"],i),
                            "CAPTURED_ACTIVE_TOOLTIP_ADDITIVE_PERCENT_NOT_FULL_FORMULA"))
        return tuple(rows)
