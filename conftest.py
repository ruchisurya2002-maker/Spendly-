"""
Root-level conftest.py.

Its only job is to guarantee the project root (this file's directory, which
contains app.py and the database/ package) is on sys.path so that test
modules under tests/ can `import app` and `import database.db` regardless
of how pytest is invoked (`pytest`, `pytest tests/...`, from any cwd).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
