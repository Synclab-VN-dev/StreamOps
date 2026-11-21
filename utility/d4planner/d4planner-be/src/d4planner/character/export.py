"""Read-only observation export for AI analysis, not a canonical/Maxroll build."""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
import time

from .repository import _scope

SCHEMA = 'd4planner-character-observations/v1'
MAX_BYTES = 512_000


def export_character(path, active_session=None):
    if not path.is_file():
        raise ValueError('CHARACTER_NO_DATA')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.5)) as db:
            db.row_factory = sqlite3.Row
            deadline = time.monotonic()+3
            db.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'equipment_current' not in tables:
                raise ValueError('CHARACTER_NO_DATA')
            scope = _scope(db)
            # Legacy data without observation scope cannot safely be combined with
            # another projection by guessing the latest capture session.
            if not scope:
                raise ValueError('CHARACTER_NO_DATA')
            session, start = scope['sessionId'], scope['startSeq']
            equipment = []
            for row in db.execute('SELECT * FROM equipment_current WHERE source_session_id=? AND source_event_seq_start>=? ORDER BY slot_family,slot_index,item_fingerprint LIMIT 257', (session,start)):
                item = json.loads(row['item_json'])
                if not isinstance(item, dict):
                    raise ValueError('CHARACTER_SOURCE_INVALID')
                equipment.append({'slot':row['slot_family'],'slotIndex':row['slot_index'],
                    'status':'observed','item':item,'fingerprint':row['item_fingerprint'],
                    'confidence':row['confidence'],'observedAt':row['observed_at'],
                    'eventSeqStart':row['source_event_seq_start'],'eventSeqEnd':row['source_event_seq_end']})
            empty = []
            if 'equipment_empty' in tables:
                empty = [dict(row) for row in db.execute('SELECT slot_family AS slot,event_seq AS eventSeq,observed_at AS observedAt FROM equipment_empty WHERE session_id=? AND event_seq>=? ORDER BY slot_family', (session,start))]
            talismans = []
            if 'talisman_observation' in tables:
                selected = {}
                for row in db.execute("SELECT * FROM talisman_observation WHERE session_id=? AND start_seq>=? AND role='equipped' ORDER BY start_seq LIMIT 257", (session,start)):
                    value = dict(row)
                    for name in ['attributes_json','set_bonuses_json']:
                        if name in value:
                            value[name.removesuffix('_json')] = json.loads(value.pop(name))
                    value.pop('session_id',None)
                    key = ('seal',) if value['kind']=='seal' else (value['kind'],value['name'],value['item_power'],value['item_type'],json.dumps(value['attributes'],sort_keys=True))
                    selected[key] = value
                    if len(talismans) == 256:
                        raise ValueError('CHARACTER_EXPORT_TOO_LARGE')
                    talismans.append(value)
                talismans = list(selected.values())
            if len(equipment)>256:
                raise ValueError('CHARACTER_EXPORT_TOO_LARGE')
            if not equipment and not talismans and not empty:
                raise ValueError('CHARACTER_NO_DATA')
            revision = db.execute('SELECT revision FROM equipment_projection_revision WHERE singleton=1').fetchone() if 'equipment_projection_revision' in tables else None
            occupied = {slot for row in equipment for slot in row['item'].get('occupied_slot_families',[row['slot']])}
            empty = [row for row in empty if row['slot'] not in occupied]
            result = {'schemaVersion':SCHEMA,'purpose':'observed-character-analysis',
                'exportedAt':datetime.now(timezone.utc).isoformat(),
                'character':{'identity':'UNVERIFIED','name':None},
                'capture':{'sessionId':session,'scopeStartEventSeq':start,
                    'freshness':'ACTIVE_SESSION' if active_session==session else 'LAST_KNOWN',
                    'equipmentRevision':revision[0] if revision else None},
                'layout':scope['layout'],'equipment':equipment,'confirmedEmptySlots':empty,
                'notObservedSlots':[s for s in scope['layout']['slots'] if s not in occupied and s not in {e['slot'] for e in empty} and not (s.startswith('ring-') and any(e['slot']=='ring' for e in equipment))],
                'talisman':{'observations':talismans,'physicalCharmPositions':'UNVERIFIED'},
                'coverage':{'skills':'NOT_CAPTURED','paragon':'NOT_CAPTURED','characterIdentity':'UNVERIFIED',
                    'ringPositions':'UNVERIFIED','legacyEmptyEvidence':'NOT_RECONSTRUCTED'}}
            if len(json.dumps(result,ensure_ascii=True).encode())>MAX_BYTES:
                raise ValueError('CHARACTER_EXPORT_TOO_LARGE')
            return result
    except sqlite3.OperationalError:
        raise ValueError('CHARACTER_SOURCE_UNAVAILABLE') from None
    except (sqlite3.DatabaseError, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('CHARACTER_SOURCE_INVALID') from None
