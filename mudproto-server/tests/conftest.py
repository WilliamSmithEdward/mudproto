"""conftest.py — shared pytest configuration for mudproto-server tests.

Adds core_logic to sys.path so all test modules can import server modules directly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core_logic"))
