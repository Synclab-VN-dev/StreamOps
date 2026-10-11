# Restrict the one-use GitHub token handoff directory without elevated audit rights.
# Invoked by start-streamops-node.ps1 before any encrypted credential is written.
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Directory
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$item = Get-Item -LiteralPath $Directory -Force -ErrorAction Stop
if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "Token handoff directory must be a real local directory."
}

# The scheduled task runs as the SAME Windows interactive user. The current
# SID avoids account-name escaping/localization issues for domain users.
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$grant = "*" + $sid + ":(OI)(CI)F"

# icacls changes the DACL only; a newly created DirectorySecurity object
# passed to Set-Acl can attempt SACL changes requiring SeSecurityPrivilege.
# Grant before removing inherited ACLs so the directory never loses owner access.
& icacls.exe $item.FullName "/grant:r" $grant "/inheritance:r" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restrict token handoff directory ACL (icacls exit $LASTEXITCODE)."
}

# Windows can give newly created directories explicit ACL entries for
# SYSTEM/Administrators/other principals, not just inherited entries.
# Remove those explicit grants/denials by SID, while retaining this user's
# explicit grant. Do not widen privileges or disable the ACL verification.
$acl = Get-Acl -LiteralPath $item.FullName -ErrorAction Stop
if (-not $acl.AreAccessRulesProtected) {
    throw "Token handoff directory still inherits permissions."
}
$existingRules = $acl.GetAccessRules(
    $true, $true, [System.Security.Principal.SecurityIdentifier]
)
$otherSids = @(
    $existingRules |
        Where-Object { $_.IdentityReference.Value -ne $sid } |
        ForEach-Object { $_.IdentityReference.Value } |
        Sort-Object -Unique
)
foreach ($otherSid in $otherSids) {
    & icacls.exe $item.FullName "/remove" ("*" + $otherSid) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to remove an unexpected token handoff ACL entry."
    }
}
# Never write the token until the final DACL is exactly owner-only.
$acl = Get-Acl -LiteralPath $item.FullName -ErrorAction Stop
$rules = $acl.GetAccessRules(
    $true, $true, [System.Security.Principal.SecurityIdentifier]
)
$ownAllow = $false
foreach ($rule in $rules) {
    if ($rule.IsInherited -or $rule.AccessControlType -ne "Allow" -or
        $rule.IdentityReference.Value -ne $sid) {
        throw "Token handoff directory has unexpected permissions."
    }
    $ownAllow = $true
}
if (-not $ownAllow) {
    throw "Token handoff directory did not grant the interactive user access."
}
