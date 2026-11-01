"""Manual immutable OBS plugin publication; never installs or controls OBS."""
import shutil

CI_SPEC = {'version': 1,
 'id': 'obs-plugin-release',
 'jobs': [{'id': 'build',
           'profile': 'windows',
           'timeout': 1800,
           'operation': 'build'},
          {'id': 'publish',
           'profile': 'linux',
           'timeout': 900,
           'operation': 'publish',
           'capability': 'external-publish',
           'secrets': {'GH_TOKEN': 'SYNCLAB_OBS_RELEASE_TOKEN'}}]}

def run(ctx):
    ctx.env["EXPECTED_VERSION"]=ctx.version or ""
    if ctx.job["operation"] in ("build","test"):
        # Build candidate plugin
        ctx.shell(r'''
pwsh scripts/e2e/issue35_build_candidate.ps1 -Configuration RelWithDebInfo
''',shell='pwsh')
        # Verify plugin DLL
        ctx.shell(r'''
$releaseRoot = Join-Path $PWD "util/obs-multi-rtmp-websocket/release/RelWithDebInfo"
$dlls = @(Get-ChildItem $releaseRoot -Recurse -File -Filter "obs-multi-rtmp.dll" -ErrorAction Stop)

if ($dlls.Count -ne 1) {
  throw "Expected exactly one obs-multi-rtmp.dll under $releaseRoot, found $($dlls.Count)."
}

$dll = $dlls[0]
$sha = (Get-FileHash $dll.FullName -Algorithm SHA256).Hash
"dll=$($dll.FullName)" >> $env:GITHUB_OUTPUT
"sha256=$sha" >> $env:GITHUB_OUTPUT

Write-Host "OBS_MULTI_RTMP_BUILD PASS"
Write-Host "DLL=$($dll.FullName)"
Write-Host "SHA256=$sha"

"### OBS Multi-RTMP Windows build" >> $env:GITHUB_STEP_SUMMARY
"" >> $env:GITHUB_STEP_SUMMARY
"- Result: PASS" >> $env:GITHUB_STEP_SUMMARY
"- Artifact: obs-multi-rtmp.dll" >> $env:GITHUB_STEP_SUMMARY
"- SHA256: $sha" >> $env:GITHUB_STEP_SUMMARY
''',shell='pwsh')
        outputs=dict(line.strip().split('=',1) for line in open(ctx.env['GITHUB_OUTPUT']) if '=' in line)
        ctx.env['BUILT_DLL']=outputs['dll'];ctx.env['BUILT_SHA']=outputs['sha256']
        # Stage artifact
        ctx.shell(r'''
New-Item -ItemType Directory -Force -Path ".streamops/issue-45-ci" | Out-Null
Copy-Item "$env:BUILT_DLL" ".streamops/issue-45-ci/obs-multi-rtmp.dll"
@"
{
  "source_commit": "$env:GITHUB_SHA",
  "configuration": "RelWithDebInfo",
  "sha256": "$env:BUILT_SHA"
}
"@ | Set-Content ".streamops/issue-45-ci/build-manifest.json" -Encoding UTF8
''',shell='pwsh')
        # Package managed Synclab release candidate
        ctx.shell(r'''
$sha = (git rev-parse HEAD).Trim()
python scripts/release/obs_plugin_package.py pack `
  --source-root util/obs-multi-rtmp-websocket `
  --source-commit $sha `
  --output-dir .streamops/obs-managed-candidate
if ($LASTEXITCODE -ne 0) { throw "Managed plugin package generation failed." }
python scripts/release/obs_plugin_package.py verify `
  --output-dir .streamops/obs-managed-candidate `
  --expected-commit $sha
if ($LASTEXITCODE -ne 0) { throw "Managed plugin package verification failed." }
''',shell='pwsh')
        ctx.artifact('.streamops/issue-45-ci','native-dll')
        ctx.artifact('.streamops/obs-managed-candidate','candidate')
        if ctx.intent=='publish':
            # Validate deliberate manual release request
            ctx.shell(r'''
if ($env:GITHUB_REF -notin @('refs/heads/master', 'refs/heads/feat/issue-47-obs-plugin-manager')) {
  throw "Manual publication is restricted to reviewed release branches."
}
if ($env:EXPECTED_VERSION -notmatch '^\d+\.\d+\.\d+\.\d+$') {
  throw "Release requires expected_version with four numeric parts."
}
$spec = Get-Content 'util/obs-multi-rtmp-websocket/buildspec.json' -Raw | ConvertFrom-Json
if ($spec.version -ne $env:EXPECTED_VERSION -or
    $spec.dependencies.'obs-studio'.version -ne '32.2.1') {
  throw "Requested release version/OBS compatibility differs from custom source."
}
''',shell='pwsh')
            # Package reviewed manual release
            ctx.shell(r'''
$sha = (git rev-parse HEAD).Trim()
python scripts/release/obs_plugin_package.py pack `
  --source-root util/obs-multi-rtmp-websocket `
  --configuration RelWithDebInfo `
  --source-commit $sha `
  --output-dir .streamops/obs-release-ready `
  --release-approved
if ($LASTEXITCODE -ne 0) { throw "Release packaging failed." }
python scripts/release/obs_plugin_package.py verify `
  --output-dir .streamops/obs-release-ready `
  --require-approved `
  --expected-version $env:EXPECTED_VERSION `
  --expected-commit $sha
if ($LASTEXITCODE -ne 0) { throw "Approved release verification failed." }
''',shell='pwsh')
            ctx.artifact('.streamops/obs-release-ready','reviewed')
    else:
        artifact=ctx.build_artifact('reviewed')
        shutil.copytree(artifact,ctx.root/'.streamops/obs-release-ready')
        ctx.env['RELEASE_REPO']='Synclab-VN-dev/StreamOps-OBS-Plugins'
        credential=ctx.env.pop('GH_TOKEN')
        ctx.env.pop('GITHUB_TOKEN',None)
        # Verify release source and payload before credentials
        ctx.shell(r'''
set -euo pipefail
[[ "$EXPECTED_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
python scripts/release/obs_plugin_package.py verify \
  --output-dir .streamops/obs-release-ready \
  --require-approved --expected-version "$EXPECTED_VERSION" \
  --expected-commit "$GITHUB_SHA"
test "$(find .streamops/obs-release-ready -maxdepth 1 -type f | wc -l)" -eq 4
''',shell='bash')
        ctx.env['GH_TOKEN']=credential
        # Publish immutable reviewed release to managed repository
        ctx.shell(r'''
set -euo pipefail
test -n "$GH_TOKEN" || { echo "Missing protected SYNCLAB_OBS_RELEASE_TOKEN." >&2; exit 1; }
tag="obs-multi-rtmp/v$EXPECTED_VERSION"
if gh release view "$tag" --repo "$RELEASE_REPO" >/dev/null 2>&1; then
  echo "Release tag already exists; refusing to replace immutable artifacts: $tag" >&2
  exit 1
fi
assets=".streamops/obs-release-ready"
archive="$assets/obs-multi-rtmp-$EXPECTED_VERSION-windows-x64.zip"
archive_sha="$(sha256sum "$archive" | cut -d ' ' -f1)"
cat > "$RUNNER_TEMP/managed-release-notes.md" <<EOF
Synclab custom OBS Multi-RTMP plugin built from reviewed StreamOps source.

Source: https://github.com/Synclab-VN-dev/StreamOps/tree/$GITHUB_SHA/util/obs-multi-rtmp-websocket
Source commit: $GITHUB_SHA
Version: $EXPECTED_VERSION
Compatibility: OBS 32.2.1 / Windows x64
License: GPL-2.0 (see LICENSE-GPL-2.0.txt)
Package SHA-256: $archive_sha
Check obs-multi-rtmp.release.json and obs-multi-rtmp.provenance.json for checksums.
EOF
gh release create "$tag" \
  "$archive" \
  "$assets/obs-multi-rtmp.release.json" \
  "$assets/obs-multi-rtmp.provenance.json" \
  "$assets/LICENSE-GPL-2.0.txt" \
  --repo "$RELEASE_REPO" --target main --draft \
  --title "Synclab custom OBS Multi-RTMP $EXPECTED_VERSION" \
  --notes-file "$RUNNER_TEMP/managed-release-notes.md"
# Keep the release invisible to consumers until all four remote assets
# have been downloaded and byte-compared against the approved payload.
remote="$RUNNER_TEMP/release-roundtrip"
mkdir -p "$remote"
gh release download "$tag" --repo "$RELEASE_REPO" --dir "$remote" \
  --pattern "obs-multi-rtmp-$EXPECTED_VERSION-windows-x64.zip" \
  --pattern "obs-multi-rtmp.release.json" \
  --pattern "obs-multi-rtmp.provenance.json" \
  --pattern "LICENSE-GPL-2.0.txt"
test "$(find "$remote" -maxdepth 1 -type f | wc -l)" -eq 4
for file in "$assets"/*; do
  cmp -s "$file" "$remote/$(basename "$file")" || {
    echo "Uploaded release asset differs from reviewed bytes: $(basename "$file")" >&2
    exit 1
  }
done
test "$(gh release view "$tag" --repo "$RELEASE_REPO" --json isDraft --jq .isDraft)" = true
gh release edit "$tag" --repo "$RELEASE_REPO" --draft=false
test "$(gh release view "$tag" --repo "$RELEASE_REPO" --json isDraft --jq .isDraft)" = false
echo "PUBLISHED_RELEASE=$tag" >> "$GITHUB_STEP_SUMMARY"
echo "SOURCE_COMMIT=$GITHUB_SHA" >> "$GITHUB_STEP_SUMMARY"
echo "APPROVED_ZIP_SHA256=$archive_sha" >> "$GITHUB_STEP_SUMMARY"
''',shell='bash')
