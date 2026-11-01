"""Component-owned CI commands migrated from the corresponding native workflows."""
CI_SPEC = {'version': 1,
 'id': 'streamops',
 'watch': ['pyproject.toml',
           'scripts/e2e/issue85*',
           'scripts/devices/a-windows/issue85*',
           'scripts/ci/*game*',
           '.github/workflows/main.yml',
           '.github/workflows/ci.py',
           'scripts/release/**',
           'scripts/server/**',
           'scripts/node/**'],
 'depends_on': ['d4planner-hud'],
 'jobs': [{'id': 'native', 'profile': 'windows', 'timeout': 2400}]}

def _run(ctx):
    if ctx.job['id'] == 'native':
        ctx.isolated_python()
        # tests.yml / windows: Install StreamOps server dependencies
        ctx.shell(r'''
python -m pip install '.[server,dev]'
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Install Playwright Chromium
        ctx.shell(r'''
python -m playwright install chromium
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Install ffmpeg
        ctx.shell(r'''
choco install ffmpeg --no-progress -y
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Build StreamOps wheel
        ctx.shell(r'''
python -m pip wheel . --no-deps -w dist
''', shell='pwsh', cwd='.')
        # tests.yml / windows: Test installed wheel outside source checkout
        ctx.shell(r'''
$env:STREAMOPS_TEST_WHEEL = (Get-ChildItem dist\*.whl | Select-Object -First 1).FullName
python -m pytest -q streamops/server/tests/test_wheel_acceptance.py
''', shell='pwsh', cwd='.')
        ctx.env['GAME_WHEEL']='success'
        ctx.env.update({'GAME_SCOPE':'true','CI_EVENT_NAME':'push'})
        # tests.yml / windows: Game G1 — Schema and seed
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/test_games_catalog.py streamops/server/tests/test_games_package.py
''', shell='pwsh', cwd='.')
        ctx.env['GAME_G1']='success'
        # tests.yml / windows: Game G2 — Provider contract
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/test_games_provider_contract.py
''', shell='pwsh', cwd='.')
        ctx.env['GAME_G2']='success'
        # tests.yml / windows: Game G3 — Static migration
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/test_games_catalog.py streamops/server/tests/test_games_installation.py
''', shell='pwsh', cwd='.')
        ctx.env['GAME_G3']='success'
        # tests.yml / windows: Game G4 — WebSocket REST and observer notify
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/test_games_api.py streamops/server/tests/test_games_steam_ws.py streamops/server/tests/test_games_status_hub.py streamops/server/tests/e2e/test_games_ws_contract.py streamops/server/tests/e2e/test_games_recovery.py
''', shell='pwsh', cwd='.')
        ctx.env['GAME_G4']='success'
        # tests.yml / windows: Game G5 — Lifecycle safety and idempotency
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/test_games_lifecycle.py streamops/server/tests/test_games_process_identity.py
''', shell='pwsh', cwd='.')
        ctx.env['GAME_G5']='success'
        # tests.yml / windows: Game G6 — Package and wheel seed
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/test_games_package.py streamops/server/tests/test_games_installation.py
''', shell='pwsh', cwd='.')
        ctx.env['GAME_G6']='success'
        # tests.yml / windows: Game observer/lifecycle race regression — 3 runs
        ctx.shell(r'''
1..3 | ForEach-Object {
  Write-Host "Game race regression iteration $_ / 3"
  python -m pytest -q streamops/server/tests/test_games_status_hub.py streamops/server/tests/test_games_lifecycle.py -k 'hub or concurrent or backpressure or resubscribe'
  if ($LASTEXITCODE -ne 0) { throw "Race regression iteration $_ failed" }
}
''', shell='pwsh', cwd='.')
        ctx.env['GAME_RACE']='success'
        # tests.yml / windows: Test StreamOps
        ctx.shell(r'''
python -m pytest -q
''', shell='pwsh', cwd='.')
        ctx.env['GAME_REGRESSION']='success'
        # tests.yml / windows: Game E2E-01 — fail-closed negative tests
        ctx.shell(r'''
$env:CI_EVENT_NAME = 'push'
$env:GAME_SCOPE = 'true'
$names = @('GAME_G1','GAME_G2','GAME_G3','GAME_G4','GAME_G5','GAME_G6',
           'GAME_WHEEL','GAME_RACE','GAME_REGRESSION','GAME_AUDIT_SELFTEST')
foreach ($name in $names) {
  [Environment]::SetEnvironmentVariable($name, 'success', 'Process')
}
$env:GAME_G4 = 'skipped'
& pwsh -NoProfile -File ./scripts/ci/verify_game_required_gates.ps1 *> $null
if ($LASTEXITCODE -eq 0) { throw 'Audit accepted SKIPPED G4 — false green' }
$env:GAME_G4 = 'success'
$env:GAME_SCOPE = 'false'
& pwsh -NoProfile -File ./scripts/ci/verify_game_required_gates.ps1 *> $null
if ($LASTEXITCODE -eq 0) { throw 'Audit accepted missing required game scope' }
$env:GAME_SCOPE = 'true'
& pwsh -NoProfile -File ./scripts/ci/verify_game_required_gates.ps1
if ($LASTEXITCODE -ne 0) { throw 'Audit rejected valid all-successful gates' }
''', shell='pwsh', cwd='.')
        ctx.env['GAME_AUDIT_SELFTEST']='success'
        # tests.yml / windows: FE-G1 — WS contract, reducer and pinned source integrity
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/test_games_ui_contract.py streamops/server/tests/test_magicpath_visual_contract.py
''', shell='pwsh', cwd='.')
        # tests.yml / windows: FE-G2 — Steam browser WebSocket regression
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/e2e/test_steam.py
''', shell='pwsh', cwd='.')
        # tests.yml / windows: FE-G3 — Games UI browser states and observer fanout
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/e2e/test_games_ui.py streamops/server/tests/e2e/test_games_fe_be_integration.py
''', shell='pwsh', cwd='.')
        # tests.yml / windows: FE-G4 — Lifecycle and reconnect recovery
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/e2e/test_games_ui.py -k 'lifecycle or reconnect or state_model'
''', shell='pwsh', cwd='.')
        # tests.yml / windows: FE-G6 — Installed wheel FE pages and asset smoke
        ctx.shell(r'''
$env:STREAMOPS_TEST_WHEEL = (Get-ChildItem dist\*.whl | Select-Object -First 1).FullName
python -m pytest -q streamops/server/tests/test_wheel_acceptance.py
''', shell='pwsh', cwd='.')
        return
    raise ValueError("UNKNOWN_JOB")


def run(ctx):
    # Every gate must succeed; audit also executes when an earlier gate fails.
    ctx.env.update({'GAME_SCOPE':'true','CI_EVENT_NAME':'push'})
    for key in ('G1','G2','G3','G4','G5','G6','WHEEL','RACE','REGRESSION','AUDIT_SELFTEST'):
        ctx.env['GAME_'+key]='not_run'
    try:
        _run(ctx)
    finally:
        ctx.shell('./scripts/ci/verify_game_required_gates.ps1', shell='pwsh')
