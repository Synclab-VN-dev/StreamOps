param([string]$Guest=(Join-Path $PSScriptRoot '../tools/build_setup_vm.ps1'))
$ErrorActionPreference='Stop'
$path=Resolve-Path $Guest
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
if($errors){throw ($errors|Out-String)}
$function=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Initialize-BuildCache'},$true)
Invoke-Expression $function.Extent.Text
$root=Join-Path ([IO.Path]::GetTempPath()) ('cache-policy-'+[guid]::NewGuid().ToString('N'))
try {
 New-Item -ItemType Directory "$root/cache/cargo-target","$root/frameworks" -Force|Out-Null
 Set-Content "$root/cache/cargo-target/compiled" 'cache'
 Set-Content "$root/frameworks/toolchain" 'retain'
 $null=Initialize-BuildCache "$root/cache"
 if(-not(Test-Path "$root/cache/cargo-target/compiled")){throw 'Normal build lost cache'}
 $null=Initialize-BuildCache "$root/cache" -Clean
 if(Test-Path "$root/cache/cargo-target"){throw 'Rebuild retained compile cache'}
 if(-not(Test-Path "$root/frameworks/toolchain")){throw 'Rebuild removed framework'}
 'Cache policy PASS: normal retained, rebuild cleared, frameworks retained'
} finally {Remove-Item -LiteralPath $root -Recurse -Force}
