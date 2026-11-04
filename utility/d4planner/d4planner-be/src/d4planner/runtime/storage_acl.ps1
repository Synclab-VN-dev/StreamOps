# Read-only shared Windows DataRoot ownership/access policy. Never changes ACLs.
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:D4PLANNER_ACL_PATH
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$sid = $identity.User.Value
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
$owned = $owner -eq $sid -or ($owner -eq 'S-1-5-32-544' -and $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
if (-not $owned) { throw 'Foreign owner' }
# OWNER RIGHTS is trusted only after validating the actual owner above.
$allowed = @($sid, 'S-1-5-18', 'S-1-5-32-544', 'S-1-3-0', 'S-1-3-4')
foreach ($entry in $acl.Access) {
    $entrySid = $entry.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($entry.AccessControlType -eq 'Allow' -and ($entry.FileSystemRights -band 0x000D0116) -ne 0 -and $entrySid -notin $allowed) {
        throw 'Foreign write access'
    }
}
