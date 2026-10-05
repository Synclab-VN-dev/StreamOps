# Imported upstream source

This directory vendors source from:

- Repository: https://github.com/davidcool/obs-multi-rtmp-websocket-support
- Commit: d81f40b769c4f1460132d8bc06207027c681e359
- Commit message: Update delete_target safety check, comprehensive README, and diagnostic suite
- Imported for: StreamOps issue #35 Gate 3 API spike
- License: GPL-2.0 (see LICENSE)

## Import policy

The source is intentionally vendored without the nested upstream `.git` directory so StreamOps owns
the reviewable history on `feat/issue-35-multirtmp-api-spike`.

The GitHub connector used for this import cannot round-trip binary blobs through the same text import
path. The following documentation-only images from the upstream commit are intentionally omitted:

- docs/install.jpg
- docs/screenshot.jpg
- docs/wechat.jpg
- docs/zhi.png

No build/runtime source, CMake input, dependency header, locale, or upstream Python diagnostic is
omitted by this binary-doc exclusion.

Do not update this directory from a moving branch. Pin a new upstream commit and record it here before
refreshing vendored source.
