"""Component-owned CI commands migrated from the corresponding native workflows."""
CI_SPEC = {'version': 1,
 'id': 'd4planner-rulekit',
 # Legacy source paths remain watched while migration is compared with master.
 'watch': ['utility/d4-rulekit/**',
           '.github/workflows/main.yml', '.github/workflows/ci.py'],
 'depends_on': [],
 'jobs': [{'id': 'schema', 'profile': 'linux', 'timeout': 900},
          {'id': 'browser',
           'profile': 'linux',
           'timeout': 1200,
           'tools': {'node': '22'}},
          {'id': 'provider',
           'profile': 'linux',
           'timeout': 600,
           'tools': {'node': '22'}},
          {'id': 'application',
           'profile': 'linux',
           'timeout': 600,
           'tools': {'node': '22'}},
          {'id': 'encrypted-fixture',
           'profile': 'linux',
           'timeout': 600,
           'manual': True,
           'capability': 'fixture',
           'secrets': {'AGE_IDENTITY_SECRET': 'MAXROLL_FIXTURE_AGE_IDENTITY'},
           'tools': {'node': '22'}}]}

def _run(ctx):
    if ctx.job['id'] == 'schema':
        ctx.isolated_python()
        # d4-rulekit.yml / schema-contract: Install isolated package with test dependencies
        ctx.shell(r'''
python -m pip install -e 'utility/d4planner/d4planner-rulekit[dev]'
''', shell='bash', cwd='.')
        # d4-rulekit.yml / schema-contract: Python compile and schema self-check
        ctx.shell(r'''
set -euo pipefail
mkdir -p artifacts/d4-rulekit
python -m compileall -q utility/d4planner/d4planner-rulekit/src/d4_rulekit
d4-rulekit schema-check --report artifacts/d4-rulekit/schema-check.json
''', shell='bash', cwd='.')
        # d4-rulekit.yml / schema-contract: Strict fixture contract validation (positive and negative)
        ctx.shell(r'''
set -euo pipefail
d4-rulekit validate utility/d4planner/d4planner-rulekit/fixtures/valid/*.json \
  --report artifacts/d4-rulekit/positive.json
set +e
d4-rulekit validate utility/d4planner/d4planner-rulekit/fixtures/invalid/*.json \
  --report artifacts/d4-rulekit/negative.json
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "Expected invalid DSL fixture exit 1, got $rc"
  exit 1
fi
python - <<'PY'
import json
from pathlib import Path
p = json.loads(Path("artifacts/d4-rulekit/positive.json").read_text())
n = json.loads(Path("artifacts/d4-rulekit/negative.json").read_text())
assert p["count"] == 4 and p["status"] == "PASS", p
assert n["count"] == 4 and n["status"] == "FAIL", n
assert all(row["status"] == "FAIL" for row in n["results"]), n
PY
''', shell='bash', cwd='.')
        # d4-rulekit.yml / schema-contract: CI-03 sourced execution contract consistency and golden reference vectors
        ctx.shell(r'''
set -euo pipefail
python -m d4_rulekit.contract_check \
  --contract utility/d4planner/d4planner-rulekit/contracts/execution-v1.json \
  --references utility/d4planner/d4planner-rulekit/references/3.2.3/ci03-reference-vectors.json \
  --report artifacts/d4-rulekit/ci03-contract.json
python - <<'PY'
import json
from pathlib import Path
report = json.loads(Path("artifacts/d4-rulekit/ci03-contract.json").read_text())
assert report["status"] == "PASS" and report["referenceCount"] >= 4, report
assert report["gameAccuracy"] == "NOT_VERIFIED_BY_CI03", report
PY
''', shell='bash', cwd='.')
        # d4-rulekit.yml / schema-contract: Contract unit and CLI integration tests
        ctx.shell(r'''
set -euo pipefail
python -m pytest -q utility/d4planner/d4planner-rulekit/tests \
  --junitxml=artifacts/d4-rulekit/junit.xml
python -m unittest discover \
  -s utility/d4planner/d4planner-rulekit/snapshot-management/tests -p test_snapshot_release.py -v
''', shell='bash', cwd='.')
        # d4-rulekit.yml / schema-contract: Build wheel and verify installed package outside repository
        ctx.shell(r'''
set -euo pipefail
python -m build --wheel utility/d4planner/d4planner-rulekit --outdir "$RUNNER_TEMP/rulekit-wheels"
python -m venv "$RUNNER_TEMP/rulekit-venv"
"$RUNNER_TEMP/rulekit-venv/bin/python" -m pip install "$RUNNER_TEMP"/rulekit-wheels/*.whl
( cd "$RUNNER_TEMP" && "$RUNNER_TEMP/rulekit-venv/bin/d4-rulekit" schema-check )
"$RUNNER_TEMP/rulekit-venv/bin/d4-rulekit" validate \
  "$GITHUB_WORKSPACE/utility/d4planner/d4planner-rulekit/fixtures/valid/skill.json"
''', shell='bash', cwd='.')
        return
    if ctx.job['id'] == 'browser':
        # d4-rulekit.yml / browser-infrastructure: Install pinned Playwright Core
        ctx.shell(r'''
npm ci
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/browser-infra')
        # d4-rulekit.yml / browser-infrastructure: Install pinned Chromium and Linux dependencies
        ctx.shell(r'''
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  npx playwright-core install --with-deps chromium
else
  npx playwright-core install chromium
fi
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/browser-infra')
        # d4-rulekit.yml / browser-infrastructure: Resolve pinned Chromium executable
        ctx.shell(r'''
set -euo pipefail
chromium_path=$(node -e "process.stdout.write(require('playwright-core').chromium.executablePath())")
test -x "$chromium_path"
echo "BROWSER_INFRA_CHROMIUM_PATH=$chromium_path" >> "$GITHUB_ENV"
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/browser-infra')
        # d4-rulekit.yml / browser-infrastructure: Unit and real headless Chromium E2E
        ctx.shell(r'''
npm test
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/browser-infra')
        return
    if ctx.job['id'] == 'provider':
        # d4-rulekit.yml / maxroll-provider: Install pinned provider and source dependency packages
        ctx.shell(r'''
npm ci
npm ci --prefix ../../snapshot-management
npm ci --prefix ../../browser-infra
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        # d4-rulekit.yml / maxroll-provider: Install Chromium pinned by Playwright lockfile
        ctx.shell(r'''
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  npx --no-install playwright-core install --with-deps chromium
else
  npx --no-install playwright-core install chromium
fi
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        # d4-rulekit.yml / maxroll-provider: Resolve pinned browser and runtime versions
        ctx.shell(r'''
set -euo pipefail
browser_path=$(node -e "process.stdout.write(require('playwright-core').chromium.executablePath())")
test -x "$browser_path"
echo "browser_path=$browser_path"
"$browser_path" --version
node --version
node -e "console.log('playwright-core ' + require('playwright-core/package.json').version)"
echo "BROWSER_INFRA_CHROMIUM_PATH=$browser_path" >> "$GITHUB_ENV"
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        # d4-rulekit.yml / maxroll-provider: Verify pinned browser compatibility and cleanup
        ctx.shell(r'''
npm run smoke:browser
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        # d4-rulekit.yml / maxroll-provider: Type declarations, unit, contract and offline synthetic E2E
        ctx.shell(r'''
npm test
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        return
    if ctx.job['id'] == 'application':
        # d4-rulekit.yml / application: Install pinned development dependencies
        ctx.shell(r'''
npm ci
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/application')
        # d4-rulekit.yml / application: Type declarations and all local application gates
        ctx.shell(r'''
npm test
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/application')
        return
    if ctx.job['id'] == 'encrypted-fixture':
        # Install pinned provider dependencies
        ctx.shell(r'''
npm ci
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        # Install verified age v1.3.2 binary
        ctx.shell(r'''
set -euo pipefail
archive="$RUNNER_TEMP/age-v1.3.2-linux-amd64.tar.gz"
curl --fail --location --silent --show-error \
  --output "$archive" \
  https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz
echo 'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10  '"$archive" | sha256sum --check
tar -xzf "$archive" -C "$RUNNER_TEMP"
chmod 700 "$RUNNER_TEMP/age/age"
echo "AGE_BIN=$RUNNER_TEMP/age/age" >> "$GITHUB_ENV"
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        # Materialize age identity without logging it
        ctx.shell(r'''
set -euo pipefail
if [[ -z "$AGE_IDENTITY_SECRET" ]]; then
  echo '::error::BLOCKED_KEY_PROVISIONING: MAXROLL_FIXTURE_AGE_IDENTITY is missing'
  exit 1
fi
umask 077
printf '%s' "$AGE_IDENTITY_SECRET" > "$RUNNER_TEMP/fixture-identity.txt"
echo "AGE_IDENTITY_FILE=$RUNNER_TEMP/fixture-identity.txt" >> "$GITHUB_ENV"
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        # Discover preinstalled Chromium
        ctx.shell(r'''
set -euo pipefail
browser=''
for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
  if command -v "$candidate" >/dev/null 2>&1; then browser="$(command -v "$candidate")"; break; fi
done
if [[ -z "$browser" ]]; then echo '::error::No preinstalled Chromium/Chrome'; exit 1; fi
"$browser" --version
echo "BROWSER_INFRA_CHROMIUM_PATH=$browser" >> "$GITHUB_ENV"
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        # Download, decrypt, verify and run full offline acceptance
        ctx.shell(r'''
set -euo pipefail
npm run e2e:real:offline -- \
  --identity "$AGE_IDENTITY_FILE" --age-bin "$AGE_BIN" \
  --chromium "$BROWSER_INFRA_CHROMIUM_PATH" --ephemeral-identity
''', shell='bash', cwd='utility/d4planner/d4planner-rulekit/providers/maxroll')
        return
    raise ValueError("UNKNOWN_JOB")


def run(ctx):
    paths = {
        'schema': ['artifacts/d4-rulekit'],
        'browser': ['utility/d4planner/d4planner-rulekit/browser-infra/artifacts'],
        'provider': ['utility/d4planner/d4planner-rulekit/providers/maxroll/artifacts'],
        'application': ['utility/d4planner/d4planner-rulekit/application/artifacts'],
        'encrypted-fixture': ['utility/d4planner/d4planner-rulekit/providers/maxroll/artifacts/'+name
                              for name in ('real.json','real.junit.xml','real-acceptance.json','offline-real-e2e.json')],
    }[ctx.job['id']]
    success = False
    try:
        _run(ctx)
        success = True
    finally:
        for path in paths:
            if (ctx.root/path).exists(): ctx.artifact(path)
            elif success and ctx.job['id'] not in ('provider','encrypted-fixture'):
                raise RuntimeError('REQUIRED_ARTIFACT_MISSING: '+path)
