"""Manual private catalog export; input stays encrypted; only approved catalog/report are uploaded."""
import json
from pathlib import Path
import tempfile

CI_SPEC = {'version': 1, 'id': 'd4planner-catalog-export', 'depends_on': [],
           'jobs': [{'id': 'validation', 'profile': 'linux', 'timeout': 300, 'tools': {'node': '22'}},
                    {'id': 'export', 'profile': 'linux', 'timeout': 900,
                     'manual': True, 'capability': 'fixture',
                     'secrets': {'AGE_IDENTITY_SECRET': 'MAXROLL_FIXTURE_AGE_IDENTITY'},
                     'tools': {'node': '22'}}]}


def run(ctx):
    if ctx.job['id'] == 'validation':
        ctx.shell('npm ci', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        ctx.python('-m', 'unittest', 'discover', '-s',
                   'utility/d4planner/d4planner-rulekit/catalog-export/tests', '-v')
        ctx.run(['node', '--test',
                 'utility/d4planner/d4planner-rulekit/providers/maxroll/tests/unit/catalog-ci.test.js',
                 'utility/d4planner/d4planner-rulekit/providers/maxroll/tests/unit/catalog-export.test.js'])
        return
    raw = ctx.variable('D4PLANNER_CATALOG_EXPORT_CONFIG')
    if not raw or len(raw) > 16384:
        raise ValueError('CATALOG_CONFIG_MISSING_OR_INVALID')
    config = json.loads(raw)
    # The workflow uploads ctx.output recursively even on failure. Keep all raw
    # config and intermediate files outside that tree for the entire operation.
    with tempfile.TemporaryDirectory(prefix='catalog-private-', dir=ctx.temp) as temporary:
        private = Path(temporary)
        filename = private / 'catalog-config.json'
        filename.touch(mode=0o600, exist_ok=False)
        filename.write_text(json.dumps(config), encoding='utf-8')
        ctx.shell('npm ci', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        ctx.shell(r'''
set -euo pipefail
archive="$RUNNER_TEMP/catalog-age.tar.gz"
curl --fail --location --silent --show-error --output "$archive" https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz
echo 'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10  '"$archive" | sha256sum --check
tar -xzf "$archive" -C "$RUNNER_TEMP"
chmod 700 "$RUNNER_TEMP/age/age"
''', shell='bash', cwd='.')
        output = private / 'catalog-output'
        ctx.run(['node', 'utility/d4planner/d4planner-rulekit/catalog-export/run.js', str(filename), str(output)],
                env={'AGE_BIN': ctx.env['RUNNER_TEMP'] + '/age/age'})
        for name in ('catalog.json', 'report.json'):
            ctx.artifact(output / name, name)
