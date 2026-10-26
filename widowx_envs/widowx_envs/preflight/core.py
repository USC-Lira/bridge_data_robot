"""Core primitives for the preflight check framework.

The framework is deliberately dependency-free (stdlib only) so that the host
half of the checks can run with the system ``python3`` on the robot desktop,
outside of the ``robonet`` container and outside of any conda/venv.

A *check* is a function that takes a :class:`Context` and returns a
:class:`CheckResult` (or a list of them, for checks that fan out over e.g.
cameras). Checks are registered with the :func:`check` decorator and run by
:func:`run_checks`, which honours declared dependencies: if a check that others
depend on fails, the dependents are skipped instead of producing a cascade of
confusing failures.
"""

from __future__ import annotations

import dataclasses
import enum
import os
import shutil
import subprocess
import sys
import time
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Union


class Status(enum.Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"

    @property
    def blocking(self) -> bool:
        """Whether this status should stop data collection from starting."""
        return self is Status.FAIL


@dataclasses.dataclass
class CheckResult:
    name: str
    status: Status
    summary: str
    remedy: str = ""
    details: dict = dataclasses.field(default_factory=dict)
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CheckResult":
        d = dict(d)
        d["status"] = Status(d["status"])
        return cls(**d)


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #

CheckFn = Callable[["Context"], Union[CheckResult, Sequence[CheckResult]]]


@dataclasses.dataclass
class Check:
    name: str
    scope: str  # "host" or "container"
    fn: CheckFn
    description: str = ""
    requires: Sequence[str] = ()
    tags: Sequence[str] = ()


_REGISTRY: "Dict[str, Check]" = {}


def check(name: str, scope: str, requires: Sequence[str] = (), tags: Sequence[str] = ()):
    """Register a preflight check under ``name``.

    ``name`` is namespaced by scope, e.g. ``host.usb_connector_chart``. Keep it
    stable: it is what teleoperators type into ``--only`` / ``--skip`` and what
    shows up in the JSON report.
    """

    if scope not in ("host", "container"):
        raise ValueError(f"unknown scope {scope!r}")

    def deco(fn: CheckFn) -> CheckFn:
        if name in _REGISTRY:
            raise ValueError(f"duplicate check name {name!r}")
        _REGISTRY[name] = Check(
            name=name,
            scope=scope,
            fn=fn,
            description=(fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else "",
            requires=tuple(requires),
            tags=tuple(tags),
        )
        return fn

    return deco


def registered_checks(scope: Optional[str] = None) -> List[Check]:
    return [c for c in _REGISTRY.values() if scope is None or c.scope == scope]


# --------------------------------------------------------------------------- #
# execution context
# --------------------------------------------------------------------------- #


class Context:
    """Everything a check needs: the expected setup, plus shell helpers."""

    def __init__(self, config, repo_root: str, verbose: bool = False):
        self.config = config
        self.repo_root = repo_root
        self.verbose = verbose
        # Checks can stash parsed artifacts here for later checks to reuse
        # (e.g. the parsed usb connector chart, the `rostopic list` output).
        self.cache: dict = {}

    # -- shell ------------------------------------------------------------- #

    def run(self, cmd: Sequence[str], timeout: float = 15.0, input: str = None):
        """Run ``cmd`` and return ``(returncode, stdout, stderr)``.

        Never raises: a missing binary comes back as returncode 127 so checks
        can report "not installed" rather than blowing up the whole run.
        """
        if self.verbose:
            print(f"  $ {' '.join(cmd)}", file=sys.stderr)
        if shutil.which(cmd[0]) is None:
            return 127, "", f"{cmd[0]}: command not found"
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                input=input,
                timeout=timeout,
                text=True,
            )
        except subprocess.TimeoutExpired:
            return 124, "", f"{' '.join(cmd)}: timed out after {timeout}s"
        return proc.returncode, proc.stdout, proc.stderr

    def have(self, binary: str) -> bool:
        return shutil.which(binary) is not None


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #


def _as_list(res) -> List[CheckResult]:
    if isinstance(res, CheckResult):
        return [res]
    return list(res)


def _selected_names(checks: Sequence[Check], only: Sequence[str]) -> Optional[set]:
    """Names matching ``only``, plus their transitive prerequisites.

    Without the closure, ``--only host.usb_connector_chart`` would skip the
    check it asked for, because its prerequisite never ran.
    """
    if not only:
        return None
    by_name = {c.name: c for c in checks}
    selected = {c.name for c in checks if any(c.name.startswith(p) for p in only)}
    pending = list(selected)
    while pending:
        chk = by_name.get(pending.pop())
        if chk is None:
            continue
        for req in chk.requires:
            if req not in selected:
                selected.add(req)
                pending.append(req)
    return selected


def run_checks(
    ctx: Context,
    scope: str,
    only: Sequence[str] = (),
    skip: Sequence[str] = (),
) -> List[CheckResult]:
    """Run every registered check for ``scope`` in registration order."""
    results: List[CheckResult] = []
    status_by_name: Dict[str, Status] = {}
    checks = registered_checks(scope)
    selected = _selected_names(checks, only)

    for chk in checks:
        if selected is not None and chk.name not in selected:
            continue
        if any(chk.name.startswith(p) for p in skip):
            results.append(
                CheckResult(chk.name, Status.SKIP, "skipped by --skip")
            )
            status_by_name[chk.name] = Status.SKIP
            continue

        unmet = [r for r in chk.requires if status_by_name.get(r) in (Status.FAIL, Status.SKIP, None)]
        if unmet:
            res = CheckResult(
                chk.name,
                Status.SKIP,
                f"prerequisite not satisfied: {', '.join(unmet)}",
                remedy=f"Fix {unmet[0]} first, then re-run.",
            )
            results.append(res)
            status_by_name[chk.name] = Status.SKIP
            continue

        started = time.time()
        try:
            produced = _as_list(chk.fn(ctx))
        except Exception as exc:  # a broken check must not hide the other checks
            produced = [
                CheckResult(
                    chk.name,
                    Status.FAIL,
                    f"check raised {type(exc).__name__}: {exc}",
                    remedy="This is a bug in the check itself, not necessarily in the robot setup.",
                )
            ]
        elapsed = time.time() - started

        # A fan-out check reports one row per item but one status for the gate.
        worst = Status.PASS
        for res in produced:
            res.duration_s = res.duration_s or elapsed / max(len(produced), 1)
            if res.status is Status.FAIL:
                worst = Status.FAIL
            elif res.status is Status.WARN and worst is not Status.FAIL:
                worst = Status.WARN
        status_by_name[chk.name] = worst
        results.extend(produced)

    return results


def worst_status(results: Iterable[CheckResult]) -> Status:
    worst = Status.PASS
    for r in results:
        if r.status is Status.FAIL:
            return Status.FAIL
        if r.status is Status.WARN:
            worst = Status.WARN
    return worst


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

_COLORS = {
    Status.PASS: "\033[32m",
    Status.WARN: "\033[33m",
    Status.FAIL: "\033[31m",
    Status.SKIP: "\033[90m",
}
_RESET = "\033[0m"
_LABELS = {
    Status.PASS: " PASS ",
    Status.WARN: " WARN ",
    Status.FAIL: " FAIL ",
    Status.SKIP: " SKIP ",
}


def _supports_color(stream) -> bool:
    return hasattr(stream, "isatty") and stream.isatty() and os.environ.get("TERM") != "dumb"


def print_report(results: Sequence[CheckResult], title: str, stream=sys.stdout) -> None:
    color = _supports_color(stream)

    def tag(status: Status) -> str:
        label = _LABELS[status]
        return f"{_COLORS[status]}[{label}]{_RESET}" if color else f"[{label}]"

    print(f"\n=== {title} ===", file=stream)
    width = max((len(r.name) for r in results), default=0)
    for r in results:
        print(f"{tag(r.status)} {r.name.ljust(width)}  {r.summary}", file=stream)
        if r.remedy and r.status in (Status.FAIL, Status.WARN):
            for line in r.remedy.splitlines():
                print(f"{' ' * 9}-> {line}", file=stream)


def print_summary(results: Sequence[CheckResult], stream=sys.stdout) -> Status:
    counts = {s: sum(1 for r in results if r.status is s) for s in Status}
    overall = worst_status(results)
    color = _supports_color(stream)
    line = (
        f"{counts[Status.PASS]} passed, {counts[Status.WARN]} warnings, "
        f"{counts[Status.FAIL]} failed, {counts[Status.SKIP]} skipped"
    )
    print(f"\n{line}", file=stream)
    if counts[Status.PASS] == 0 and counts[Status.FAIL] == 0 and counts[Status.WARN] == 0:
        # Nothing actually ran - never report this as a green light.
        msg = "PREFLIGHT INCONCLUSIVE - no checks ran, so nothing was verified."
        print(f"{_COLORS[Status.WARN]}{msg}{_RESET}" if color else msg, file=stream)
        return Status.WARN
    if overall is Status.FAIL:
        msg = "PREFLIGHT FAILED - do not start data collection until the failures above are fixed."
    elif overall is Status.WARN:
        msg = "PREFLIGHT PASSED WITH WARNINGS - read them before collecting."
    else:
        msg = "PREFLIGHT PASSED - you are clear to collect."
    print(f"{_COLORS[overall]}{msg}{_RESET}" if color else msg, file=stream)
    return overall
