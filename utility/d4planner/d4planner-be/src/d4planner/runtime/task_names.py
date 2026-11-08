"""Task identities produced by current D4Planner runtime/diagnostic code.

No generic D4Planner prefix match: retired probes and unrelated tasks are not
migration blockers. Dynamic identities must match the complete source-defined
format (including identifier length and an actual runtime task suffix).
"""
import re

# WindowsRuntime.task_name / _interactive_task_specs and probe/supervisor callers.
RUNTIME_TASK_NAMES = frozenset({
    'D4Planner-Supervisor', 'D4Planner-NVDA', 'D4Planner-NVDA-Restart',
    'D4Planner-NVDA-Stop', 'D4Planner-D4', 'D4Planner-Tolk-Probe',
    'D4Planner-Input-Marker-Probe',
})
_FIXED = {name.casefold() for name in RUNTIME_TASK_NAMES}
_ISOLATED = re.compile(
    r'D4Planner-Isolated-[0-9a-f]{12}-(?:' + '|'.join(
        re.escape(name.removeprefix('D4Planner-')) for name in sorted(RUNTIME_TASK_NAMES)
    ) + r')', re.IGNORECASE | re.ASCII)
# keyboard_capture_diagnostic._relay_ssh_to_interactive uses uuid4().hex[:16].
_DIAGNOSTIC = re.compile(r'D4Planner-F11-Diagnostic-[0-9a-f]{16}', re.IGNORECASE | re.ASCII)


def is_current_task_name(name: str) -> bool:
    """Windows task names are case-insensitive; prefixes/substrings never suffice."""
    return (name.casefold() in _FIXED or _ISOLATED.fullmatch(name) is not None
            or _DIAGNOSTIC.fullmatch(name) is not None)
