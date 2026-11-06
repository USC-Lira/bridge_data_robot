"""Starting, watching and stopping the robonet container.

Used by preflight.py (to bring the container up once the host checks pass)
and by stop_container.py. Stdlib only, like the rest of the host side.

Two rules shape this module:

* The container runs **detached** (``docker compose up -d``). Its output is
  shown in a separate terminal window running ``docker compose logs -f``, so
  closing that window never stops the arm driver.
* Nothing here stops a running container without the person confirming it,
  because stopping the arm driver turns the motors off and the arm drops.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

from widowx_envs.preflight.core import CheckResult, Context, Status

ROW = "session.container"
READY_TIMEOUT_S = 120
# Records which Dockerfile/requirements the last preflight-built image came from.
BUILD_RECORD = os.path.expanduser("~/.cache/widowx_preflight/image_inputs.json")
# PID of the shell inside the log window, so stop() can close that window.
LOG_WINDOW_PID = os.path.expanduser("~/.cache/widowx_preflight/log_window.pid")


# --------------------------------------------------------------------------- #
# docker compose helpers
# --------------------------------------------------------------------------- #


def compose_env(repo_root: str, config) -> Dict[str, str]:
    env = dict(os.environ)
    env["USB_CONNECTOR_CHART"] = os.path.join(repo_root, config.usb_connector_chart)
    # The $DATA mount in docker-compose.yml, so it is the folder preflight checked.
    env["DATASET_ROOT"] = os.path.expanduser(config.dataset_root)
    return env


def compose(repo_root: str, config, args: Sequence[str], capture=True, timeout=None):
    """Run ``docker compose <args>`` from the repo root with USB_CONNECTOR_CHART set."""
    cmd = ["docker", "compose", *args]
    kwargs = dict(cwd=repo_root, env=compose_env(repo_root, config), text=True, timeout=timeout)
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        proc = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        return 124, "", f"{' '.join(cmd)}: timed out"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def container_running(repo_root: str, config) -> bool:
    rc, out, _ = compose(
        repo_root, config, ["ps", "--status", "running", "-q", config.compose_service], timeout=60
    )
    return rc == 0 and bool(out.strip())


def data_mount_source(repo_root: str, config) -> Optional[str]:
    """Host folder the running container has mounted as $DATA, if any."""
    rc, out, _ = compose(repo_root, config, ["ps", "-q", config.compose_service], timeout=60)
    cid = out.strip().splitlines()[0] if rc == 0 and out.strip() else ""
    if not cid:
        return None
    fmt = ('{{range .Mounts}}{{if eq .Destination "/home/robonet/trainingdata"}}'
           '{{.Source}}{{end}}{{end}}')
    try:
        src = subprocess.run(["docker", "inspect", "-f", fmt, cid], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return src or None


def rostopics(repo_root: str, config) -> List[str]:
    rc, out, _ = compose(
        repo_root,
        config,
        ["exec", "-T", config.compose_service, "bash", "-lic", "rostopic list"],
        timeout=30,
    )
    if rc != 0:
        return []
    return [l.strip() for l in out.splitlines() if l.strip().startswith("/")]


# --------------------------------------------------------------------------- #
# image freshness
# --------------------------------------------------------------------------- #


def _inputs_hash(repo_root: str) -> str:
    h = hashlib.sha256()
    for rel in ("widowx_envs/Dockerfile", "widowx_envs/requirements.txt"):
        path = os.path.join(repo_root, rel)
        if os.path.exists(path):
            with open(path, "rb") as f:
                h.update(rel.encode() + b"\0" + f.read())
    return h.hexdigest()


def _image_id(image: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["docker", "image", "inspect", "-f", "{{.Id}}", image],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out or None


def build_reason(repo_root: str, image: str) -> Optional[str]:
    """Why the image must be (re)built, or None if it can be used as is.

    The code under widowx_envs/ is mounted into the container, so only the
    Dockerfile and requirements.txt need a rebuild. An image built outside
    preflight has no record; it is trusted, because rebuilding it would redo
    catkin_make for nothing.
    """
    image_id = _image_id(image)
    if image_id is None:
        return f"image {image} does not exist yet"
    try:
        with open(BUILD_RECORD) as f:
            record = json.load(f)
    except (OSError, ValueError):
        return None
    if record.get("image_id") == image_id and record.get("inputs") != _inputs_hash(repo_root):
        return "widowx_envs/Dockerfile or requirements.txt changed since the last build"
    return None


def _record_build(repo_root: str, image: str) -> None:
    image_id = _image_id(image)
    if not image_id:
        return
    os.makedirs(os.path.dirname(BUILD_RECORD), exist_ok=True)
    with open(BUILD_RECORD, "w") as f:
        json.dump({"image_id": image_id, "inputs": _inputs_hash(repo_root),
                   "built": datetime.datetime.now().isoformat(timespec="seconds")}, f)


# --------------------------------------------------------------------------- #
# extra terminal windows (container log, VR controls card)
# --------------------------------------------------------------------------- #


def open_window(title: str, inner: str, pid_file: str, cwd: str, env=None,
                size: Optional[str] = None) -> Optional[str]:
    """Run the shell command ``inner`` in a new terminal window.

    The window's shell writes its PID to ``pid_file`` so close_window() can
    close it later. Returns the terminal used, or None if there is no desktop
    to open one on (e.g. over SSH).
    """
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None
    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    inner = f"echo $$ > {_sh(pid_file)}; " + inner
    # Tag the window's processes, so close_window() can tell them from an
    # unrelated process that reused the PID. An environment variable survives
    # bash exec'ing its last command; the command line does not.
    env = dict(env or os.environ)
    env[WINDOW_TAG_VAR] = _window_tag(pid_file)
    geo = [f"--geometry={size}"] if size else []
    candidates = [
        ("gnome-terminal", ["gnome-terminal", f"--title={title}", *geo, "--", "bash", "-c", inner]),
        ("konsole", ["konsole", "-p", f"tabtitle={title}", "-e", "bash", "-c", inner]),
        ("xfce4-terminal", ["xfce4-terminal", f"--title={title}", *geo, "-x", "bash", "-c", inner]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", "-c", inner]),
        ("xterm", ["xterm", "-T", title, *(["-geometry", size] if size else []), "-e", "bash", "-c", inner]),
    ]
    for binary, cmd in candidates:
        if shutil.which(binary):
            try:
                subprocess.Popen(
                    cmd, cwd=cwd, env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True,
                )
                return binary
            except OSError:
                continue
    return None


WINDOW_TAG_VAR = "WIDOWX_PREFLIGHT_WINDOW"


def _window_tag(pid_file: str) -> str:
    return os.path.basename(pid_file)


def close_window(pid_file: str) -> bool:
    """Close a window opened by open_window(), if it is still open.

    Only kills the PID if its environment carries this window's tag, so a PID
    that was recycled by an unrelated process is never killed.
    """
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        os.remove(pid_file)
    except OSError:
        pass
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            environ = f.read().split(b"\0")
    except OSError:
        return False
    if f"{WINDOW_TAG_VAR}={_window_tag(pid_file)}".encode() not in environ:
        return False
    try:
        # The shell leads its own process group (new session in the terminal):
        # this ends it and whatever it runs, and the window closes.
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def open_log_window(repo_root: str, config) -> Optional[str]:
    """Show ``docker compose logs -f`` in a new terminal window.

    Closing the window only closes the view. If the container dies on its own,
    the window stays open on the last messages; stop() closes it when the
    container is stopped on purpose.
    """
    inner = (
        f"cd {_sh(repo_root)} && docker compose logs -f --tail 200 {config.compose_service}; "
        "echo; echo '[the robonet container stopped]'; read -r -p 'Press Enter to close. '"
    )
    return open_window("robonet (container output)", inner, LOG_WINDOW_PID, repo_root,
                       env=compose_env(repo_root, config))


def close_log_window() -> bool:
    return close_window(LOG_WINDOW_PID)


def _sh(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


# --------------------------------------------------------------------------- #
# start / wait / stop
# --------------------------------------------------------------------------- #


def wait_until_ready(repo_root: str, config, timeout: Optional[float] = None) -> Tuple[bool, List[str]]:
    """Wait for the arm and every expected camera topic to be advertised."""
    timeout = READY_TIMEOUT_S if timeout is None else timeout
    wanted = [config.arm_joint_states_topic] + [c.image_topic for c in config.cameras]
    deadline = time.time() + timeout
    missing = wanted
    while time.time() < deadline:
        topics = set(rostopics(repo_root, config))
        missing = [t for t in wanted if t not in topics]
        if not missing:
            return True, []
        time.sleep(3)
    return False, missing


def hold_arm_warning() -> str:
    return (
        "!! HOLD THE ARM. Stopping the container turns the arm's motors off and the\n"
        "!! arm drops onto the table unless it is resting in its sleep pose."
    )


def go_to_sleep(repo_root: str, config) -> bool:
    """Move the arm to its sleep pose (go_sleep inside the container)."""
    rc, _, _ = compose(
        repo_root, config,
        ["exec", "-T", config.compose_service, "bash", "-lic", "go_sleep"],
        capture=False, timeout=120,
    )
    return rc == 0


def stop(repo_root: str, config) -> bool:
    service = config.compose_service
    rc1, _, _ = compose(repo_root, config, ["stop", service], capture=False, timeout=120)
    rc2, _, _ = compose(repo_root, config, ["rm", "-f", service], capture=False, timeout=60)
    close_log_window()
    return rc1 == 0 and rc2 == 0


def start(ctx: Context, force_build: bool) -> List[CheckResult]:
    """Build if needed, start detached, open the log window, wait for ROS."""
    repo_root, config = ctx.repo_root, ctx.config
    out: List[CheckResult] = []

    reason = "--build was given" if force_build else build_reason(repo_root, config.compose_image)
    if reason:
        print(f"\n[preflight] Building the {config.compose_service} image ({reason}).", flush=True)
        print("[preflight] This can take several minutes; the build output follows.\n", flush=True)
        rc, _, _ = compose(repo_root, config, ["build", config.compose_service], capture=False)
        if rc != 0:
            return [CheckResult(f"{ROW}.build", Status.FAIL, "docker compose build failed",
                                remedy="Scroll up for the error. To see it again:\n"
                                "  docker compose build --progress=plain robonet")]
        _record_build(repo_root, config.compose_image)
        out.append(CheckResult(f"{ROW}.build", Status.PASS, f"image built ({reason})"))

    print(f"\n[preflight] Starting the {config.compose_service} container...", flush=True)
    rc, _, err = compose(repo_root, config, ["up", "-d", config.compose_service], timeout=300)
    if rc != 0:
        out.append(CheckResult(ROW, Status.FAIL, "docker compose up -d failed",
                               remedy=err.strip()[-1500:]))
        return out

    window = open_log_window(repo_root, config)
    logs = f"docker compose logs -f {config.compose_service}"
    if window:
        print(f"[preflight] Container output is in a new {window} window.", flush=True)
    else:
        print(f"[preflight] No desktop to open a window on. Watch the output with:\n  {logs}", flush=True)

    print(f"[preflight] Waiting up to {READY_TIMEOUT_S}s for the arm and camera topics...", flush=True)
    ready, missing = wait_until_ready(repo_root, config)
    if not ready:
        out.append(CheckResult(
            ROW, Status.FAIL,
            f"started, but not ready after {READY_TIMEOUT_S}s (missing: {', '.join(missing)})",
            remedy=f"Look at the container output ({'the log window' if window else logs}) for the\n"
            "first error. The container checks below say more.",
        ))
        return out
    where = f"output in the {window} window" if window else f"output: {logs}"
    out.append(CheckResult(ROW, Status.PASS, f"{config.compose_service} started and ready ({where})"))
    return out


def ensure_running(ctx: Context, host_failed: List[CheckResult], force_build: bool) -> List[CheckResult]:
    """Make sure the container is up for the container checks.

    Starts it only if no host check failed. Never restarts a running one
    without asking, and only when the usb chart changed during this run.
    """
    repo_root, config = ctx.repo_root, ctx.config
    if container_running(repo_root, config):
        stale = []
        if ctx.cache.get("chart_changed"):
            stale.append("usb_connector_chart.yml changed in this run (the container reads it only at startup)")
        mounted = data_mount_source(repo_root, config)
        wanted = os.path.realpath(os.path.expanduser(config.dataset_root))
        if mounted and os.path.realpath(mounted) != wanted:
            stale.append(f"it saves data to {mounted}, not {wanted} (started with an older docker-compose.yml)")
        if not stale:
            return [CheckResult(ROW, Status.PASS, f"{config.compose_service} already running")]
        msg = "the running container is out of date: " + "; ".join(stale)
        if not ctx.interactive:
            return [CheckResult(ROW, Status.WARN, msg,
                                remedy="Restart the container to apply it: python3 stop_container.py,\n"
                                "then re-run preflight.")]
        print(f"\n[preflight] {msg}.", flush=True)
        print(hold_arm_warning(), flush=True)
        if ctx.ask("Move the arm to its sleep pose and restart the container now?", default=False):
            go_to_sleep(repo_root, config)
            ctx.ask("Arm resting or held? Press Enter to stop the container", default=True, yes_no=False)
            stop(repo_root, config)
            return start(ctx, force_build)
        return [CheckResult(ROW, Status.WARN, msg + "; not restarted",
                            remedy="Restart later with: python3 stop_container.py, then re-run preflight.")]

    if host_failed:
        names = ", ".join(sorted({r.name for r in host_failed}))
        return [CheckResult(ROW, Status.SKIP, f"not started: fix the host failures first ({names})")]
    return start(ctx, force_build)
