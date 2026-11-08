# Report Issue: local configuration

Gateway is included in the backend and started by native HUD on demand. There is no
HTTP service to install, domain to choose, user login provider or GitHub App.

## One file in DataRoot

Create `<DataRoot>\private\report-config.json`. With the normal Windows installation:
`%LOCALAPPDATA%\StreamOps\D4Planner\private\report-config.json`.
Use the application's selected DataRoot if customized, not the install directory.

```json
{
  "githubToken": "REPLACE_WITH_YOUR_FINE_GRAINED_PAT",
  "recipient": "REPLACE_WITH_MAINTAINER_AGE_PUBLIC_RECIPIENT",
  "maxBytes": 10000000
}
```

The placeholders are deliberately not working credentials. Use UTF-8 JSON, no comments,
no extra fields. The 10 MB example is an operator choice; the ceiling is 64,000,000 bytes.
Configuration is re-read on every submission; restarting the app is unnecessary.
Do not set `D4PLANNER_REPORT_ACCESS_TOKEN`, a Gateway URL or a port. Old remote-Gateway
environment variables are no longer used by the native bridge.

Create a fine-grained PAT for **Synclab-VN-dev/StreamOps only**, with **Issues: read/write**
and **Contents: read/write**, a suitable expiration, and any organization approval
required. The PAT owner must have repository access; a token cannot grant permissions
the account lacks. Report issues, comments and assets are created under this account.
[GitHub token permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).

Keep this file in the private folder with access limited to the installing user and
trusted Windows administrators. Never paste its contents into an issue, chat or logs.
The archive includes only selected diagnostic sources; this configuration is excluded.
The package content scanner rejects JSON containing report credentials.

## One-time repository preparation by the maintainer

Log encryption still requires an **age X25519 public recipient**. The maintainer supplies
that public key and retains the corresponding private key outside the app/config/repo.
A GitHub PAT cannot replace this key. Do not invent a recipient: reports would be unreadable.

The existing dedicated release must have:

- Tag: `d4planner-bug-report-logs`
- Name: `D4Planner Bug Report Logs`
- Prerelease: true; Draft: false; Immutable: false; not latest

The backend resolves and validates its numeric ID automatically. It never creates or
unlocks a release while sending a report. A missing/inaccessible release reports
`DIAGNOSTIC_RELEASE_NOT_CONFIGURED`; repository settings remain unchanged.

The existing hourly maintenance workflow is separate from the local HTTP server. Its
`DIAGNOSTIC_BOT_ID` must identify the reporting PAT owner for assets it is allowed to
clean, and `DIAGNOSTIC_RELEASE_ID` must match this release. It does not automatically
clean reports from arbitrary other PAT owners. No cleanup or release provisioning is
performed by this setup guide. Multiple reporting accounts require an explicit
maintenance configuration extension before claiming universal 24-hour retention.

## Use and recovery

Open Report Issue, complete the form, select logs, preview and consent, then Submit.
Success returns the actual Issue URL only after encrypted asset verification.
The raw D4Planner Event Log remains unavailable until capture-session binding exists;
FE/BE/Rule Kit logs are supported. No DB or configuration file is exported.

- `REPORT_NOT_CONFIGURED`: create the file at the path above.
- `INVALID_REPORT_CONFIG`: check fields, JSON, owner/access, size and linked paths.
- `RECIPIENT_NOT_CONFIGURED`: obtain a valid age public recipient.
- `GITHUB_401`: replace an invalid/expired PAT.
- `GITHUB_403`: check repo permissions and organization approval.
- `DIAGNOSTIC_RELEASE_NOT_CONFIGURED`: ask the maintainer to provision/check the release.
- `GATEWAY_409` or transport uncertainty: keep the draft and retry the same report;
  do not create a replacement issue manually unless the outcome has been reconciled.

Changing recipient after sealing a report is blocked. Keep the same PAT account when
retrying; the shared ledger rejects a report owned by another account. Never remove the
`report-gateway.sqlite3` state while a report is unresolved.

Tests use fake GitHub responses and synthetic data. They do not prove real permissions,
release existence, encryption-key custody or successful production submission.
