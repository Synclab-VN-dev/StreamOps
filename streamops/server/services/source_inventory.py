"""Typed discovery. GET only reads OBS and native operating-system inventory."""
from ..scene_profiles import SOURCE_CATALOG
from ..platform.windows.obs_inventory import windows_inventory


def discover(client, native_provider=windows_inventory):
    native = native_provider()
    errors = list(native.get('errors', []))
    inputs, kinds, monitors = [], [], []
    try:
        inputs = client.get_input_list()
        kinds = client.get_input_kind_list()
        monitors = client.get_monitor_list()
    except Exception as exc:
        errors.append(f'OBS inventory unavailable: {exc}')
    options = {}
    for source_type, spec in SOURCE_CATALOG.items():
        fields = options[source_type] = {}
        for field in spec['setting_fields']:
            if field == 'window': fields[field] = list(native.get('windows', []))
            elif field == 'video_device_id': fields[field] = list(native.get('cameras', []))
            elif field == 'device_id': fields[field] = list(native.get('capture' if source_type == 'audio_input' else 'render', []))
            elif field == 'source_name': fields[field] = [{'label': i['inputName'], 'value': i['inputName']} for i in inputs]
            elif field == 'monitor_id': fields[field] = [{'label': m['monitorName'], 'value': m['monitorName'].rsplit('(', 1)[0]} for m in monitors]
        matching = [i for i in inputs if (i.get('unversionedInputKind') or i.get('inputKind')) == spec['obs_kind']]
        for item in matching[:1]:
            for field in list(fields):
                try:
                    values = client.get_input_properties_list_property_items(item['inputName'], field)
                    if values:
                        fields[field] = [{'label': p['itemName'], 'value': p['itemValue']} for p in values if p.get('itemEnabled', True) and p.get('itemValue') not in ('', 'DUMMY')]
                except Exception:
                    # Native inventory remains usable when a plugin lacks a property.
                    pass
    return {'inputs':[{'name':i['inputName'],'kind':i.get('unversionedInputKind') or i.get('inputKind')} for i in inputs], 'input_kinds':kinds, 'options':options, 'errors':errors}
