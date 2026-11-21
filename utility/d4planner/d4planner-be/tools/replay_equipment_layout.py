"""Private recorded-event acceptance. Does not contact a game or mutate its DB.

python tools/replay_equipment_layout.py --events /private/events.jsonl \
  --layouts tests/fixtures/equipment/verified_equipment_layouts.json --output /private/replay
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from d4planner.character.equipment.projector import EquipmentProjector
from d4planner.character.repository import EquipmentRepository, ReadOnlyEquipmentRepository
from d4planner.character.current_view import current_view
from d4planner.runtime.diagnostics import MemoryDiagnosticsSink


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--events',type=Path,required=True)
    ap.add_argument('--layouts',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    raw=args.events.read_bytes();events=[json.loads(l) for l in raw.decode().splitlines()]
    with tempfile.TemporaryDirectory() as tmp:
        repo=EquipmentRepository(Path(tmp)/'character.db');sink=MemoryDiagnosticsSink(component='equipment')
        projector=EquipmentProjector(repo,sink);projector.equipment_layouts=json.loads(args.layouts.read_text())
        for event in events:projector.consume(event)
        result=ReadOnlyEquipmentRepository(repo.path).projection_snapshot()
        view=current_view(result.rows,result.revision[0] if result.revision else None,result.layout)
        (args.output/'current.json').write_text(json.dumps(view,indent=2,ensure_ascii=False))
        (args.output/'diagnostics.json').write_text(json.dumps(sink.records,indent=2))
        report={'eventsSha256':sha256(raw).hexdigest(),'events':len(events),'layout':view['layout'],
                'items':len(view['items']),'weaponSlots':sorted(i['slotFamily'] for i in view['items'] if i['slotFamily'] in {'ranged','main_hand','off_hand'}),
                'scope':'offline replay; not live Windows/character identity validation'}
        (args.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

if __name__=='__main__':main()
