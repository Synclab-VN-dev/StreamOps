"""Compatibility entrypoint for local change-detector regression (no Actions calls)."""
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    root=Path(__file__).resolve().parents[2]
    raise SystemExit(subprocess.call([sys.executable,'-m','unittest','discover','-s',
                                     str(root/'.github/workflows/tests'),'-p','test_ci.py','-v'],cwd=root))
