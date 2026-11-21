"""Observed topology, not authenticated character identity or calculation binding.

Only a verified provider catalogue can expand observed weapons into a complete
layout. The header fingerprint prevents mixing two observed inventory contexts;
missing/ambiguous identity stays explicitly unverified.
"""
from hashlib import sha256

BASE_SLOTS = ['helm', 'chest', 'gloves', 'pants', 'boots', 'amulet', 'ring-1', 'ring-2']
WEAPONS = ('ranged', 'main_hand', 'off_hand')


def new_scope(session, seq, context_key=None):
    return {'sessionId': session, 'startSeq': seq, 'contextKey': context_key,
            'weapons': {}, 'header': [], 'layout': {'status': 'UNKNOWN', 'slots': BASE_SLOTS}}


def observe_header(state, text, seq):
    # Inventory header observed on A: CHARACTER / left shoulder / right shoulder /
    # name / title / Weapon Damage. Party/chat names outside this frame do not count.
    header = state.get('header', [])
    if text == 'CHARACTER':
        state['header'] = [text]
        return False
    if not header:
        return False
    header.append(text)
    if text == 'Weapon Damage' or len(header) >= 6:
        state['header'] = []
        if (len(header) == 6 and header[:3] == ['CHARACTER', 'Left shoulder button', 'Right shoulder button']
                and header[-1] == 'Weapon Damage' and header[3] and header[4]):
            key = sha256(header[3].encode()).hexdigest()
            if state.get('contextKey') is not None and state['contextKey'] != key:
                state.update(new_scope(state['sessionId'], seq, key))
                return True
            state['contextKey'] = key
    return False


def detect_layout(state, layouts):
    observed = state['weapons']
    slots = [s for s in WEAPONS if s in observed]
    status = 'OBSERVED' if slots else 'UNKNOWN'
    if (observed and isinstance(layouts, dict) and layouts.get('status') == 'READY'
            and layouts.get('schemaVersion') == 'd4planner-equipment-layout/v1'):
        candidates = []
        for entry in layouts.get('classes', []):
            weapons = [s for s in entry.get('slots', []) if s.get('slotFamily') in (*WEAPONS, 'unsupported_weapon')]
            if not weapons or any(s['slotFamily'] == 'unsupported_weapon' for s in weapons):
                continue
            if all(any(s['slotFamily'] == family and kind in s['itemTypes'] for s in weapons)
                   for family, kind in observed.items()):
                candidates.append(tuple(s for s in WEAPONS if any(w['slotFamily'] == s for w in weapons)))
        if candidates and len(set(candidates)) == 1:
            slots = list(candidates[0]); status = 'VERIFIED'
    state['layout'] = {'status': status, 'slots': BASE_SLOTS[:5] + slots + BASE_SLOTS[5:]}
    return state['layout']
