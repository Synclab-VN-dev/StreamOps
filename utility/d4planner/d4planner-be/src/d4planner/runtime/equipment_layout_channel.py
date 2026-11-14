"""Bounded, owner-bound layout messages on the existing capture lifetime pipe."""
from __future__ import annotations
import hashlib
import json
import queue
import re

MAX_FRAME = 65536
PROTOCOL = 'd4planner-capture-layout/v1'


def layout_digest(layouts):
    if not isinstance(layouts, dict) or layouts.get('schemaVersion') != 'd4planner-equipment-layout/v1' or layouts.get('status') != 'READY':
        raise ValueError('Invalid layout schema/status')
    provenance = layouts.get('provenance')
    if not isinstance(provenance, dict) or provenance.get('providerId') != 'maxroll' or not isinstance(provenance.get('snapshotId'), str) or not provenance['snapshotId']:
        raise ValueError('Invalid layout provenance')
    for key in ('manifestSha256', 'coverageSha256'):
        if not re.fullmatch('[a-f0-9]{64}', str(provenance.get(key, ''))):
            raise ValueError('Invalid layout hash')
    classes = layouts.get('classes')
    if not isinstance(classes, list) or not classes:
        raise ValueError('Missing class layouts')
    for entry in classes:
        if not isinstance(entry, dict) or not isinstance(entry.get('className'), str) or not isinstance(entry.get('slots'), list) or not entry['slots']:
            raise ValueError('Invalid class layout')
        for slot in entry['slots']:
            if not isinstance(slot, dict) or slot.get('slotFamily') not in {None, 'main_hand', 'off_hand', 'unsupported_weapon'} or not isinstance(slot.get('itemTypes'), list) or any(not isinstance(t, str) for t in slot['itemTypes']):
                raise ValueError('Invalid equipment slot')
    encoded = json.dumps(layouts, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(encoded) > MAX_FRAME // 2:
        raise ValueError('Layout too large')
    return hashlib.sha256(encoded).hexdigest()


def encode_layout(owner_token, layouts):
    digest = layout_digest(layouts)
    frame = {'protocol': PROTOCOL, 'ownerToken': owner_token, 'digest': digest, 'layouts': layouts}
    encoded = json.dumps(frame, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    if len(encoded) > MAX_FRAME:
        raise ValueError('Frame too large')
    return encoded, digest


class LayoutInbox:
    """Pipe thread only queues; the supervisor thread mutates the projector."""
    def __init__(self, owner_token):
        self.owner_token = owner_token
        self.pending = queue.Queue(maxsize=1)
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, chunk):
        for part in chunk.splitlines(keepends=True):
            end = part.endswith(b'\n')
            if not self.discarding:
                self.buffer.extend(part)
                if len(self.buffer) > MAX_FRAME:
                    self.buffer.clear(); self.discarding = True
            if end:
                if not self.discarding:
                    try:
                        frame = json.loads(self.buffer)
                        if (frame['protocol'] == PROTOCOL and frame['ownerToken'] == self.owner_token
                                and frame['digest'] == layout_digest(frame['layouts'])):
                            try: self.pending.get_nowait()
                            except queue.Empty: pass
                            self.pending.put_nowait(frame)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        pass
                self.buffer.clear(); self.discarding = False

    def take(self):
        try: return self.pending.get_nowait()
        except queue.Empty: return None
