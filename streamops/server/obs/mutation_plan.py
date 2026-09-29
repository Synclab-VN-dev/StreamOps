"""Copy-on-write OBS snapshot: reconciliation produces commands without setters.

Negative item IDs are plan-local references, resolved after CreateInput/Item.
The adapter only implements operations used by the scene reconciler.
"""
from copy import deepcopy


class PlannedObs:
    def __init__(self, client, scene):
        self.client, self.scene = client, scene
        self.commands = []
        self.cache = {}
        self.next_id = -1
        self.scenes = deepcopy(client.get_scene_list())
        self.inputs = deepcopy(client.get_input_list())
        self.items = deepcopy(client.get_scene_item_list(scene)) if any(s['sceneName'] == scene for s in self.scenes) else []
        self.items.sort(key=lambda item: item['sceneItemIndex'])
        self.video = deepcopy(client.get_video_settings())

    def read(self, method, *args):
        key = (method, *args)
        if key not in self.cache:
            self.cache[key] = deepcopy(getattr(self.client, method)(*args))
        return deepcopy(self.cache[key])

    def write(self, method, *args, **kwargs):
        self.commands.append((method, deepcopy(args), deepcopy(kwargs), None))

    def get_version(self): return self.read('get_version')
    def get_input_kind_list(self): return self.read('get_input_kind_list')
    def get_monitor_list(self): return self.read('get_monitor_list')
    def get_input_default_settings(self, kind):
        return self.read('get_input_default_settings', kind) if hasattr(self.client, 'get_input_default_settings') else {}
    def get_video_settings(self): return deepcopy(self.video)
    def get_scene_list(self): return deepcopy(self.scenes)
    def get_input_list(self): return deepcopy(self.inputs)
    def get_scene_item_list(self, scene): return deepcopy(self.items)
    def get_stream_status(self): return {'outputActive': False}
    def get_record_status(self): return {'outputActive': False}

    def set_video_settings(self, value):
        self.video.update(value)
        self.write('set_video_settings', value)

    def create_scene(self, scene):
        self.scenes.append({'sceneName': scene})
        self.write('create_scene', scene)

    def _new_item(self, name, enabled):
        item_id = self.next_id
        self.next_id -= 1
        self.items.append({'sceneItemId': item_id, 'sourceName': name, 'sceneItemEnabled': enabled, 'sceneItemIndex': len(self.items)})
        self.cache[('get_scene_item_transform', self.scene, item_id)] = {}
        return item_id

    def create_input(self, scene, name, kind, settings, *, enabled=True):
        item_id = self._new_item(name, enabled)
        self.inputs.append({'inputName': name, 'inputKind': kind, 'unversionedInputKind': kind})
        self.cache[('get_input_settings', name)] = deepcopy(settings)
        for method, default in [('get_input_mute', None), ('get_input_volume', {}), ('get_input_audio_tracks', {}), ('get_input_audio_sync_offset', None)]:
            self.cache[(method, name)] = default
        self.commands.append(('create_input', (scene, name, kind, deepcopy(settings)), {'enabled': enabled}, item_id))
        return item_id

    def create_scene_item(self, scene, name, *, enabled=True):
        item_id = self._new_item(name, enabled)
        self.commands.append(('create_scene_item', (scene, name), {'enabled': enabled}, item_id))
        return item_id

    def remove_scene_item(self, scene, item_id):
        self.items = [i for i in self.items if i['sceneItemId'] != item_id]
        self._renumber()
        self.write('remove_scene_item', scene, item_id)

    def _renumber(self):
        for index, item in enumerate(self.items): item['sceneItemIndex'] = index

    def set_scene_item_index(self, scene, item_id, index):
        item = next(i for i in self.items if i['sceneItemId'] == item_id)
        self.items.remove(item)
        self.items.insert(index, item)
        self._renumber()
        self.write('set_scene_item_index', scene, item_id, index)

    def set_scene_item_enabled(self, scene, item_id, enabled):
        next(i for i in self.items if i['sceneItemId'] == item_id)['sceneItemEnabled'] = enabled
        self.write('set_scene_item_enabled', scene, item_id, enabled)

    def get_scene_item_transform(self, scene, item_id): return self.read('get_scene_item_transform', scene, item_id)
    def set_scene_item_transform(self, scene, item_id, value):
        self.cache[('get_scene_item_transform', scene, item_id)] = deepcopy(value)
        self.write('set_scene_item_transform', scene, item_id, value)

    def get_input_settings(self, name): return self.read('get_input_settings', name)
    def set_input_settings(self, name, settings, *, overlay=True):
        self.cache[('get_input_settings', name)] = {**(self.get_input_settings(name) if overlay else {}), **settings}
        self.write('set_input_settings', name, settings, overlay=overlay)

    def get_input_mute(self, name): return self.read('get_input_mute', name)
    def get_input_volume(self, name): return self.read('get_input_volume', name)
    def get_input_audio_sync_offset(self, name): return self.read('get_input_audio_sync_offset', name)
    def get_input_audio_tracks(self, name): return self.read('get_input_audio_tracks', name)
    def set_input_mute(self, name, value): self.write('set_input_mute', name, value)
    def set_input_volume_db(self, name, value): self.write('set_input_volume_db', name, value)
    def set_input_audio_sync_offset(self, name, value): self.write('set_input_audio_sync_offset', name, value)
    def set_input_audio_tracks(self, name, value): self.write('set_input_audio_tracks', name, value)

    def execute(self, client, ownership):
        ids = {}
        for method, args, kwargs, result_id in self.commands:
            resolved = list(args)
            if method.startswith(('set_scene_item_', 'remove_scene_item')):
                resolved[1] = ids.get(resolved[1], resolved[1])
            result = getattr(client, method)(*resolved, **kwargs)
            if result_id is not None:
                ids[result_id] = result
                ownership.remember(client, result)
            elif method == 'remove_scene_item':
                ownership.forget(resolved[1])
