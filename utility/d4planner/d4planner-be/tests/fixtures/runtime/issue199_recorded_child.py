"""VM-only OS-ingress surrogate. Load all runtime code from the installed package.

No injected layout, mock RuleKit, patched projector, or NVDA/game launch. The real
managed daemon owns its singleton, lifetime pipe and owner-bound layout receiver.
Only Supervisor.run's OS/game loop is replaced by deterministic recorded ingress.
"""
import json
import os
from pathlib import Path
import sys
import time

payload = Path(os.environ['D4_TEST_PACKAGE_PAYLOAD'])
sys.path.insert(0, str(payload/'backend/site-packages'))
from d4planner import daemon
from d4planner.runtime.events.store import EventStore
from d4planner.runtime.events.model import EventDraft
from d4planner.runtime.model import RuntimeState
from d4planner.runtime.store import atomic_write_json
from d4planner.runtime.supervisor import Supervisor


class RecordedSupervisor(Supervisor):
    def run(self):
        assert self.equipment_projector.equipment_layouts is None
        self.store = EventStore.create(self.paths, silent=True, metadata={'mode':'recorded-ingress-installed-package'})
        self.status.state = RuntimeState.DEGRADED
        self.status.detail = 'VM recorded ingress; no live game or NVDA'
        self._persist_status()
        events = [json.loads(line) for line in Path(os.environ['D4_TEST_CAPTURE_EVENTS']).read_text(encoding='utf-8').splitlines()]
        events = [r for r in events if r['type'] in ('speech.raw','input.marker.raw')]
        completed=set()
        try:
            while not self.stop_event.is_set():
                self._flush_ingress(include_marker=False)
                for phase in ('before','after'):
                    request=self.paths.root/f'{phase}.request'
                    if phase in completed or not request.exists(): continue
                    for row in events:
                        if self.stop_event.is_set(): return 0
                        data=json.loads(row['data_json'])
                        self._pending_ingress=[EventDraft(row['type'],data,row['timestamp'])]
                        assert self._flush_ingress(include_marker=False)==1
                        if data.get('text')=='Unequip' and row['event_seq']==513:
                            atomic_write_json(self.paths.root/f'{phase}-staff-terminal.json',{
                                'sourceSeq':513,'rows':self.equipment_projector.repository.list_equipment()})
                        time.sleep(.002)
                    atomic_write_json(self.paths.root/f'{phase}-done.json',{
                        'events':len(events),'rows':self.equipment_projector.repository.list_equipment(),
                        'layout':self.status.extras.get('equipmentLayout'),
                        'error':self.status.last_error})
                    completed.add(phase)
                time.sleep(.02)
            return 0
        finally: self.store.close()


daemon.Supervisor = RecordedSupervisor
raise SystemExit(daemon.main(sys.argv[1:]))
