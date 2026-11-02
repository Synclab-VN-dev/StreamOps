"""OBS-owned policy/package regression and unapproved native candidate."""
import importlib.util
CI_SPEC = {'version':1,'id':'obs-plugin',
           'watch':['scripts/release/obs_plugin_package.py','scripts/e2e/issue35_build_candidate.ps1',
                    'streamops/server/tests/test_obs_plugin_release_harness.py',
                    'streamops/server/tests/test_obs_plugin_release_workflow_policy.py',
                    'streamops/server/tests/conftest.py',
                    'streamops/server/platform/windows/obs_plugin/**',
                    'streamops/server/services/obs_plugin_release_source.py','.github/workflows/main.yml','.github/workflows/ci.py'],
           'jobs':[{'id':'regression','profile':'linux','timeout':300},
                   {'id':'candidate','profile':'windows','timeout':1800}]}

def run(ctx):
    if ctx.job['id']=='regression':
        ctx.isolated_python()
        # Shared StreamOps conftest imports Pillow and the OBS websocket client.
        ctx.python('-m','pip','install','pytest==9.1.1','PyYAML==6.0.3',
                   'Pillow==13.0.0','websockets==17.1')
        ctx.python('-m','pytest','-q',
                   'streamops/server/tests/test_obs_plugin_release_workflow_policy.py',
                   'streamops/server/tests/test_obs_plugin_release_harness.py')
        return
    spec=importlib.util.spec_from_file_location('obs_product',ctx.root/'util/obs-multi-rtmp-websocket/ci.release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.run(ctx)
