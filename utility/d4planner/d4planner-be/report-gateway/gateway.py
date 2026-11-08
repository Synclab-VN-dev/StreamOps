"""Compatibility entrypoint for maintenance and existing contract tests.

The reviewed service now ships in the backend for the Owner-approved local gateway.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from d4planner.reporting.gateway import *  # noqa: F401,F403
