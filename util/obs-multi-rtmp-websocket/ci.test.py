"""Unapproved native candidate, sharing the product build implementation."""
import importlib.util
CI_SPEC = {'version':1,'id':'obs-plugin',
           'watch':['scripts/release/obs_plugin_package.py','scripts/e2e/issue35_build_candidate.ps1',
                    'streamops/server/tests/test_obs_plugin_release_harness.py','.github/workflows/main.yml','.github/workflows/ci.py'],
           'jobs':[{'id':'candidate','profile':'windows','timeout':1800}]}

def run(ctx):
    spec=importlib.util.spec_from_file_location('obs_product',ctx.root/'util/obs-multi-rtmp-websocket/ci.release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.run(ctx)
