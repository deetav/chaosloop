"""Private child-process protocol for doctor
 stdout contains exactly one JSON value"""

import json
import sys
from contextlib import redirect_stdout

from ..runner import trial
from .doctor import fingerprint
from .specs import load_scenario


def main() -> int:
    try:
        with redirect_stdout(sys.stderr):
            ref = load_scenario(sys.argv[1])
            limit = None if sys.argv[3] == "none" else float(sys.argv[3])
            result = trial(ref.factory, seed=1234, max_steps=int(sys.argv[2]), max_time=limit)
        print(json.dumps(fingerprint(result), allow_nan=False))
        return 0
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
