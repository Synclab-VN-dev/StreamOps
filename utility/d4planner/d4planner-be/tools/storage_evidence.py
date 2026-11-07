"""Phase-local evidence: a failed Setup never invalidates an earlier S9 result."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PHASE_CASES = {
    'python': ['UDR-01', 'UDR-02', 'UDR-03', 'UDR-06', 'UDR-07', 'UDR-09'],
    'migration': ['UDR-06', 'UDR-07'],
    'launcher': ['UDR-02'],
    'logging': ['UDR-04'],
    'report-issue': ['UDR-05'],
    'setup': ['UDR-08'],
}

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def load_verified(directory, head):
    directory = Path(directory).resolve()
    report = json.loads((directory / 'report.json').read_text())
    if report.get('source', {}).get('sourceHead', report.get('head')) != head:
        raise ValueError('evidence source HEAD mismatch')
    for phase in report.get('phases', {}).values():
        artifacts = phase.get('artifacts', {})
        if phase.get('status') in {'PASS', 'FAIL'} and not artifacts:
            raise ValueError('executed phase lacks evidence hashes')
        for relative, expected in artifacts.items():
            path = (directory / relative).resolve()
            if not path.is_relative_to(directory) or digest(path) != expected:
                raise ValueError('evidence missing, changed or outside evidence directory')
    return report

def attach(cases, native):
    phases = native.get('phases', {})
    for case in cases:
        relevant = {name: phases[name] for name, ids in PHASE_CASES.items()
                    if case['id'] in ids and name in phases}
        case['nativeEvidence'] = relevant
        states = [phase.get('status', 'NOT_RUN') for phase in relevant.values()]
        case['nativeStatus'] = ('FAIL' if 'FAIL' in states else
                                'PASS' if states and all(s == 'PASS' for s in states) else 'NOT_RUN')
        # Native crate tests are regression evidence, not the full acceptance gate.
        if case['id'] in {'UDR-05', 'UDR-08'}:
            case['status'] = case['nativeStatus']
        case['ticketGate'] = 'NOT_RUN'
        case['gateReason'] = 'Requires integrated acceptance and owner MAN evidence; see phase scope'
