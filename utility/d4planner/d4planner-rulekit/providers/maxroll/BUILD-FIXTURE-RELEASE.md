# Encrypted build/output test fixture

The GB-E1-ATT reference pairs for Issue #134 are distributed as encrypted test data, not as a
StreamOps software release. No plaintext build or Character Stats fixture is stored in this
repository.

## Pinned artifact

- Release: [`test-fixture/enc-e2e-20261023-r01`](https://github.com/Synclab-VN-dev/StreamOps/releases/tag/test-fixture/enc-e2e-20261023-r01)
- Ciphertext: [`testdata-r01.zip.age`](https://github.com/Synclab-VN-dev/StreamOps/releases/download/test-fixture/enc-e2e-20261023-r01/testdata-r01.zip.age)
- Checksum: [`testdata-r01.zip.age.sha256`](https://github.com/Synclab-VN-dev/StreamOps/releases/download/test-fixture/enc-e2e-20261023-r01/testdata-r01.zip.age.sha256)
- Ciphertext SHA-256: `94e9bc3c494cdc66f02fd272faf7fcbe59ca3cd68d308acef5c550a05394e107`
- Encrypted size: `111399` bytes
- Package manifest SHA-256 after decryption: `7cef606f80ac875fb7c676f9fd3bad4b5499e299e02c3143b2295b87c259d803`
- Source private pair-manifest SHA-256: `c04629bde372b3b05604c0c57e3d78ba23f6a85bac85e41ebdb5a915a7dc644b`

The package contains two input/output pairs. Both use input contract
`maxroll-native-build-export/v1`, output contract
`maxroll-character-stats-attestation/v1`, and package contract
`streamops-encrypted-build-stats-fixture/v1`. G1 through G4 passed for both pairs. Outputs remain
`OBSERVED`; this artifact does not approve a Golden or verify game formulas.

## Download and decrypt

Obtain the age identity through the separately controlled private-key channel. Never commit it,
pass it on a command line that may be logged, or copy it into an artifact.

```bash
curl --fail --location --output testdata-r01.zip.age \
  https://github.com/Synclab-VN-dev/StreamOps/releases/download/test-fixture/enc-e2e-20261023-r01/testdata-r01.zip.age
curl --fail --location --output testdata-r01.zip.age.sha256 \
  https://github.com/Synclab-VN-dev/StreamOps/releases/download/test-fixture/enc-e2e-20261023-r01/testdata-r01.zip.age.sha256
sha256sum --check testdata-r01.zip.age.sha256
age --decrypt --identity /private/path/to/fixture.agekey \
  --output /private/work/testdata-r01.zip testdata-r01.zip.age
unzip -t /private/work/testdata-r01.zip
unzip /private/work/testdata-r01.zip -d /private/work/extracted
sha256sum /private/work/extracted/testdata-r01/manifest.json
```

Before extraction, consumers must reject absolute paths, `..` components, and backslash-based path
escapes. After extraction, verify the package-manifest SHA above and every input/stats SHA recorded
inside `manifest.json`. The encrypted package's `README.md` documents the private inventory and
local comparison flow. Delete decrypted ZIP and extracted plaintext after use.

To recapture runtime observations from an input, use the approved offline snapshot and the
`build:attest` command documented in [BUILD-ATTESTATION.md](BUILD-ATTESTATION.md). Compare the new
observation with its paired stats file by exact metric ID and provenance; do not treat the expected
file as calculation input. Generic Import Phase B is not part of this artifact.
