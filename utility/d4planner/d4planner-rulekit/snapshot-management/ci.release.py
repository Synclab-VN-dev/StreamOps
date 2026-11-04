"""Snapshot release entrypoint, shared by local ci.py and Actions."""
import importlib.util

CI_SPEC = {'version': 1, 'id': 'd4planner-snapshots',
           'depends_on': ['d4planner-rulekit'],
           'jobs': [
               {'id': 'pair', 'profile': 'linux', 'timeout': 7200,
                'operation': 'build', 'capability': 'private-build',
                'secrets': {'AGE_IDENTITY_SECRET': 'MAXROLL_FIXTURE_AGE_IDENTITY'},
                'tools': {'node': '22'}},
               {'id': 'publish', 'profile': 'linux', 'timeout': 900,
                'operation': 'publish', 'capability': 'publish'}]}


def run(ctx):
    filename = ctx.root / 'utility/d4planner/d4planner-rulekit/snapshot-management/release/pipeline.py'
    spec = importlib.util.spec_from_file_location('snapshot_release_pipeline', filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.run(ctx)
    except module.ReleaseBlocked as error:
        # Use the invoking engine's Blocked type without importing a second engine.
        engine = __import__(ctx.__class__.__module__, fromlist=['Blocked'])
        raise engine.Blocked(str(error)) from None
