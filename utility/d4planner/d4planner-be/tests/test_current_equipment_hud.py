"""Current observations reach the durable HUD without a Target or verified identity."""
import asyncio
from pathlib import Path

from d4planner.character.repository import EquipmentRepository
from d4planner.character.models import EquipmentObservation, ParsedItem
from d4planner.production import ProductionBackendRuntime

class RuleKit:
    async def start(self): return {'calculationAvailability': 'UNAVAILABLE', 'workerGeneration': 1}
    async def stop(self): pass

def runtime(root):
    return ProductionBackendRuntime({'childInstanceId': 'test-current', 'generation': 1,
        'dataDir': str(root/'state'), 'targetFolder': str(root/'targets'),
        'wsEndpoint': {'host': '127.0.0.1', 'port': 0}, 'credential': 'x'*40}, rulekit=RuleKit())

def write_item(repo, seq=1):
    repo.commit_event(session_id='synthetic', event_seq=seq, updated_at='2026-11-11T00:00:00Z',
        observation=EquipmentObservation('chest', None,
            ParsedItem('Synthetic Chest', 'Unique Chest Armor', 900, affixes=[{'text': '+101 Intelligence'}], effects_raw=['Example effect']),
            '2026-11-11T00:00:00Z', 'synthetic', seq, seq, 'HIGH', 'synthetic-chest'))

def test_saved_current_without_target_survives_restart_and_capture_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('D4PLANNER_CAPTURE_PROBE_ONLY', '1')
    repo = EquipmentRepository(tmp_path/'state'/'character.db'); write_item(repo)
    async def run():
        for _ in range(2):
            be = runtime(tmp_path)
            await be.start()
            try:
                hud = be.store.latest_authoritative()
                current = hud['currentEquipment']
                assert current['items'][0]['name'] == 'Synthetic Chest'
                assert current['items'][0]['itemPower'] == 900
                assert current['items'][0]['affixes'] == ['+101 Intelligence']
                assert current['identity'] == 'UNVERIFIED'
                assert hud['context']['target'] is None
                assert hud['score']['status'] == 'NO_DATA'
                assert hud['equipment'] == []
                await be.capture_health_changed('ERROR')
                assert be.store.latest_authoritative()['currentEquipment']['items'] == current['items']
                # Current data must satisfy the same public schema as native reads.
                import json, jsonschema
                schema = json.loads((Path(__file__).parents[1]/'contracts/release1/v1/schemas/hud.schema.json').read_text())
                jsonschema.Draft202012Validator(schema).validate(be.store.latest_authoritative())
            finally: await be.stop()
    asyncio.run(run())

def test_revision_refresh_and_missing_source_keep_saved_items(tmp_path, monkeypatch):
    monkeypatch.setenv('D4PLANNER_CAPTURE_PROBE_ONLY', '1')
    async def run():
        be = runtime(tmp_path); await be.start()
        try:
            assert be.store.latest_authoritative()['currentEquipment']['items'] == []
            repo = EquipmentRepository(tmp_path/'state'/'character.db'); write_item(repo)
            await be.refresh_current_equipment()
            first = be.store.latest_authoritative()
            assert len(first['currentEquipment']['items']) == 1
            await be.refresh_current_equipment()
            assert be.store.latest_authoritative()['hudRevision'] == first['hudRevision']
            # Loss of the source must not invent unequipped slots or clear saved items.
            repo.path.rename(repo.path.with_suffix('.saved'))
            await be.refresh_current_equipment()
            latest = be.store.latest_authoritative()
            assert latest['currentEquipment']['sourceState'] == 'UNAVAILABLE'
            assert latest['currentEquipment']['items'] == first['currentEquipment']['items']
        finally: await be.stop()
    asyncio.run(run())

def test_corrupt_source_retains_last_known_and_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv('D4PLANNER_CAPTURE_PROBE_ONLY', '1')
    repo = EquipmentRepository(tmp_path/'state'/'character.db'); write_item(repo)
    async def run():
        be = runtime(tmp_path); await be.start()
        try:
            saved = be.store.latest_authoritative()['currentEquipment']['items']
            import sqlite3
            with sqlite3.connect(repo.path) as db:
                original = db.execute('select item_json from equipment_current').fetchone()[0]
                db.execute("update equipment_current set item_json='broken'")
            await be.refresh_current_equipment()
            assert be.store.latest_authoritative()['currentEquipment']['sourceState'] == 'UNAVAILABLE'
            assert be.store.latest_authoritative()['currentEquipment']['items'] == saved
            with sqlite3.connect(repo.path) as db:
                db.execute('update equipment_current set item_json=?', (original,))
            await be.refresh_current_equipment()
            assert be.store.latest_authoritative()['currentEquipment']['sourceState'] == 'READY'
        finally: await be.stop()
    asyncio.run(run())

def test_fresh_missing_source_then_available_and_busy_preserves_current(tmp_path, monkeypatch):
    """Source availability is independent of whether any observation exists."""
    monkeypatch.setenv('D4PLANNER_CAPTURE_PROBE_ONLY', '1')
    async def run():
        be = runtime(tmp_path); await be.start()
        try:
            path = tmp_path/'state'/'character.db'
            assert not path.exists()
            current = be.store.latest_authoritative()['currentEquipment']
            assert current['sourceState'] == 'UNAVAILABLE'
            assert current['items'] == []
            repo = EquipmentRepository(path); write_item(repo)
            await be.refresh_current_equipment()
            saved = be.store.latest_authoritative()['currentEquipment']
            assert saved['sourceState'] == 'READY'
            from d4planner.character.repository import ReadOnlyEquipmentRepository, EquipmentRepositoryTransient
            with monkeypatch.context() as patch:
                def busy(_self):
                    raise EquipmentRepositoryTransient('EQUIPMENT_DB_BUSY')
                patch.setattr(ReadOnlyEquipmentRepository, 'projection_snapshot', busy)
                await be.refresh_current_equipment()
                current = be.store.latest_authoritative()['currentEquipment']
                assert current['sourceState'] == 'BUSY'
                assert current['items'] == saved['items']
            await be.refresh_current_equipment()
            hud = be.store.latest_authoritative()
            assert hud['currentEquipment']['sourceState'] == 'READY'
            assert hud['currentEquipment']['items'] == saved['items']
            assert hud['context']['target'] is None
            assert hud['equipment'] == []
            assert hud['score']['status'] == 'NO_DATA'
        finally: await be.stop()
    asyncio.run(run())
