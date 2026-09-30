"""Durable scene-item ownership, separate from the user's desired-state profile."""
from hashlib import sha256
import json
from pathlib import Path

from ..errors import SceneOperationError
from ..profile_store import SceneProfileStore


class ProfileOwnership:
    def __init__(self, root: Path):
        self.root = root

    def session(self, client, profile):
        context = client.get_scene_collection_list() if hasattr(client, 'get_scene_collection_list') else {'currentSceneCollectionName': 'test'}
        scene = next((s for s in client.get_scene_list() if s['sceneName'] == profile['obs_scene_name']), {})
        key = f"{getattr(client, 'host', 'test')}:{getattr(client, 'port', 0)}:{context.get('currentSceneCollectionName')}:{profile['id']}"
        path = self.root / (sha256(key.encode()).hexdigest() + '.json')
        return OwnershipSession(path, scene.get('sceneUuid'), profile['obs_scene_name'])


class OwnershipSession:
    def __init__(self, path, scene_uuid, scene_name):
        self.path, self.scene_uuid, self.scene_name = path, scene_uuid, scene_name
        self.entries = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding='utf-8'))
                if raw.get('scene_uuid') == scene_uuid:
                    self.entries = raw['items']
            except (ValueError, KeyError, TypeError, OSError) as exc:
                raise SceneOperationError('Ownership ledger is unreadable; no OBS mutation is safe.') from exc

    def owns(self, item):
        entry = self.entries.get(str(item['sceneItemId']))
        return bool(entry and entry['name'] == item['sourceName'] and entry.get('uuid') == item.get('sourceUuid'))

    def remember(self, client, item_id):
        scene = next(s for s in client.get_scene_list() if s['sceneName'] == self.scene_name)
        self.scene_uuid = scene.get('sceneUuid')
        item = next(i for i in client.get_scene_item_list(self.scene_name) if i['sceneItemId'] == item_id)
        self.entries[str(item_id)] = {'name': item['sourceName'], 'uuid': item.get('sourceUuid')}
        self.save()

    def forget(self, item_id):
        self.entries.pop(str(item_id), None)
        self.save()

    def save(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        SceneProfileStore._atomic_write(self.path, {'schema_version': 1, 'scene_uuid': self.scene_uuid, 'items': self.entries})


def memory_ownership(client, profile):
    """Standalone callers may reuse one client; the service always supplies disk storage."""
    sessions = getattr(client, '_profile_ownership', None)
    if sessions is None:
        sessions = client._profile_ownership = {}
    if profile['id'] not in sessions:
        session = OwnershipSession.__new__(OwnershipSession)
        session.path, session.scene_uuid, session.scene_name = None, None, profile['obs_scene_name']
        session.entries = {}
        sessions[profile['id']] = session
    return sessions[profile['id']]
