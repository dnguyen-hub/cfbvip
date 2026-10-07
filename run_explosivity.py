"""Run the Explosive Opportunity Finder directly from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from cfbvip.features.explosive_opportunity.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

