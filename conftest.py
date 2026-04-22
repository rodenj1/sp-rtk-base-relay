"""Root conftest.py for pytest configuration.

This file ensures that the project root is added to sys.path,
making the 'tests' package discoverable for pytest runs.
This is needed for 'from tests.fixtures...' style imports to work.
"""

import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
