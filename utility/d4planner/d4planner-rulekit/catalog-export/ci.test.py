"""Manual private catalog export; wrapper transports credentials and ciphertext only."""
import json

CI_SPEC = {'version': 1, 'id': 'd4planner-catalog-export', 'depends_on': [],
           'jobs': [{'id': 'export', 'profile': 'linux', 'timeout': 900,
                     'manual': True, 'capability': 'fixture',
                     'secrets': {'AGE_IDENTITY_SECRET': 'MAXROLL_FIXTURE_AGE_IDENTITY'},
                     'tools': {'node': '22'}}]}


def run(ctx):
    raw = ctx.variable('D4PLANNER_CATALOG_EXPORT_CONFIG')
    if not raw or len(raw) > 16384:
        raise ValueError('CATALOG_CONFIG_MISSING_OR_INVALID')
    config = json.loads(raw)
    filename = ctx.output / 'catalog-config.json'
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
    output = ctx.temp / 'catalog-ciphertext'
    ctx.run(['node', 'utility/d4planner/d4planner-rulekit/catalog-export/run.js', str(filename), str(output)],
            env={'AGE_BIN': ctx.env['RUNNER_TEMP'] + '/age/age'})
    for name in ('catalog.json.age', 'report.json'):
        ctx.artifact(output / name, name)
