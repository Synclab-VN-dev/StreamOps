# Encrypted multi-class test fixture

The independently observed class fixtures for Issue #134 are distributed as encrypted test data.
No plaintext input, expected Character Stats, source evidence, or decryption identity is stored in
this repository or attached to the public Release.

## Pinned artifact

- Release: [`test-fixture/enc-e2e-20261024-r02`](https://github.com/Synclab-VN-dev/StreamOps/releases/tag/test-fixture/enc-e2e-20261024-r02)
- Ciphertext: [`testdata-r02.zip.age`](https://github.com/Synclab-VN-dev/StreamOps/releases/download/test-fixture/enc-e2e-20261024-r02/testdata-r02.zip.age)
- Checksum: [`testdata-r02.zip.age.sha256`](https://github.com/Synclab-VN-dev/StreamOps/releases/download/test-fixture/enc-e2e-20261024-r02/testdata-r02.zip.age.sha256)
- Ciphertext SHA-256: `34eab25b83e335ed06fd2cf33b5ce23a6fedf1a68ba3f8a99d3c67e8d9c313de`
- Encrypted size: `458491` bytes
- Package manifest SHA-256 after decryption: `309d5fe55b7aae48bfa5ac6e04b2c94eabc08e624bdf7410f86322c37610952b`
- Package contract: `streamops-encrypted-multiclass-fixture/v1`

The immutable prerelease contains eight input/output pairs, one per pinned-engine class. Outputs
remain `OBSERVED`; the package does not verify Diablo IV formulas or prove all catalog combinations.

## Download and verify

Obtain the age identity through the separately controlled private-key channel. Never commit it,
print it, include it in command output, or upload it as an artifact.

```bash
curl --fail --location --output testdata-r02.zip.age \
  https://github.com/Synclab-VN-dev/StreamOps/releases/download/test-fixture/enc-e2e-20261024-r02/testdata-r02.zip.age
curl --fail --location --output testdata-r02.zip.age.sha256 \
  https://github.com/Synclab-VN-dev/StreamOps/releases/download/test-fixture/enc-e2e-20261024-r02/testdata-r02.zip.age.sha256
sha256sum --check testdata-r02.zip.age.sha256
age --decrypt --identity /private/path/to/fixture.agekey \
  --output /private/work/testdata-r02.zip testdata-r02.zip.age
unzip -t /private/work/testdata-r02.zip
```

Before extraction, reject absolute paths, `..` components, and backslash path escapes. After
extraction, verify `manifest.json` against the pinned package-manifest SHA and verify every file
entry in that manifest. Remove the decrypted ZIP and extracted directory after use.

The publish checkpoint performed an independent GitHub download, ciphertext verification,
decryption, safe extraction, manifest/file verification, and temporary-data cleanup. The Release
contains exactly the ciphertext and its checksum.
