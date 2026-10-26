"""Pre-collection checks for the LiraLab WidowX station.

See ``preflight.py`` for the entrypoint and ``docs/preflight.md`` for the
rationale and the list of checks.

Importing this package is intentionally cheap: the host half runs under the
system python3 with no ROS and no venv, so nothing here may import rospy,
numpy or anything else outside the standard library at module level.
"""

__all__ = ["config", "core"]
