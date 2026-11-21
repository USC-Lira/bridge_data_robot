#!/usr/bin/env python3
"""Check the rig before collecting (and start the robonet container if needed).

    python3 preflight.py --conf conf_test          # a conf from configs/, by name
    python3 preflight.py --conf configs/conf_test.py
    python3 preflight.py --help                    # all options

Shortcut for widowx_envs/widowx_envs/preflight/preflight.py, which still works.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "widowx_envs"))

from widowx_envs.preflight.preflight import main  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
