"""Component-owned CI commands migrated from the corresponding native workflows."""
CI_SPEC = {'version': 1,
 'id': 'game-manager-visual',
 'watch': [],
 'depends_on': ['streamops'],
 'jobs': [{'id': 'golden', 'profile': 'windows', 'timeout': 1200, 'tools': {'node': '24'}}]}

def run(ctx):
    if ctx.job['id'] == 'golden':
        ctx.isolated_python()
        ctx.env['STREAMOPS_VISUAL_ENFORCE_APPROVAL']='1'
        ctx.env['STREAMOPS_VISUAL_ARTIFACTS']=str(ctx.temp/'game-manager-visual')
        # game-manager-visual.yml / fe-g5-magicpath-visual: Install browser and integration test dependencies
        ctx.shell(r'''
python -m pip install '.[server,dev]'
''', shell='pwsh', cwd='.')
        # game-manager-visual.yml / fe-g5-magicpath-visual: Install Playwright Chromium
        ctx.shell(r'''
python -m playwright install chromium
''', shell='pwsh', cwd='.')
        # game-manager-visual.yml / fe-g5-magicpath-visual: Install isolated pinned-reference renderer
        ctx.shell(r'''
npm install --ignore-scripts --no-audit --no-fund
''', shell='pwsh', cwd='streamops/server/tests/visual_magicpath/reference_source')
        # game-manager-visual.yml / fe-g5-magicpath-visual: Install updated independent MagicPath V2 review renderer
        ctx.shell(r'''
npm install --ignore-scripts --no-audit --no-fund
''', shell='pwsh', cwd='streamops/server/tests/visual_magicpath/reference_source_v2')
        # game-manager-visual.yml / fe-g5-magicpath-visual: Build immutable original MagicPath reference preview
        ctx.shell(r'''
npm run build
''', shell='pwsh', cwd='streamops/server/tests/visual_magicpath/reference_source')
        # game-manager-visual.yml / fe-g5-magicpath-visual: Build independent updated MagicPath V2 preview
        ctx.shell(r'''
npm run build
''', shell='pwsh', cwd='streamops/server/tests/visual_magicpath/reference_source_v2')
        # game-manager-visual.yml / fe-g5-magicpath-visual: Verify original MagicPath source revision and immutable preview hashes
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/test_magicpath_visual_contract.py
''', shell='pwsh', cwd='.')
        # game-manager-visual.yml / fe-g5-magicpath-visual: FE-G5 — Render and compare at 360, 390, 768, 1440 + states
        ctx.shell(r'''
python -m pytest -q streamops/server/tests/e2e/test_magicpath_visual.py
''', shell='pwsh', cwd='.')
        ctx.artifact(ctx.temp/'game-manager-visual')
        return
    raise ValueError("UNKNOWN_JOB")
