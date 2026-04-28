import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database
from agents import competition_intelligence_agent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the StitchFlow Labs competition intelligence refresh."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh even if the latest weekly snapshot is still fresh.",
    )
    args = parser.parse_args()

    database.init_db()
    summary = competition_intelligence_agent.run(force=args.force)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
