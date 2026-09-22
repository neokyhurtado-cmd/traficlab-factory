from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from jev_shadow.engine import evaluate_shadow
from jev_shadow.provider import DisabledProvider, TypeSafeJevProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Jev in advisory shadow mode.")
    parser.add_argument("input", nargs="?", help="JSON task-state file; stdin when omitted")
    parser.add_argument(
        "--provider",
        choices=("disabled", "jev"),
        default="disabled",
        help="Provider. 'jev' uses TypeSafe's official SDK and TYPESAFE_API_KEY.",
    )
    parser.add_argument("--out", help="Optional JSON output path")
    args = parser.parse_args()

    text = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    raw = json.loads(text)
    provider = TypeSafeJevProvider() if args.provider == "jev" else DisabledProvider()
    decision = evaluate_shadow(raw, provider=provider).as_dict()
    rendered = json.dumps(decision, indent=2, ensure_ascii=False)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
