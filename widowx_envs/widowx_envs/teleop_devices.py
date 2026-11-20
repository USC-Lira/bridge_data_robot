"""Input devices for teleoperated data collection.

The env and the teleop policy talk to a device through this interface instead
of to a specific piece of hardware, so other devices (keyboard, SpaceMouse)
can feed the same collection pipeline and produce the same datasets.

A device provides two things:

* **Session events**, by name: ``start`` (start recording a trajectory),
  ``end_trajectory``, ``save``, ``discard``, ``neutral`` (arm to neutral before
  recording), ``end_session``, and ``confirm`` / ``cancel`` for the end-session
  question. ``snapshot()`` reads them all at once, so one loop iteration sees a
  consistent state.
* **Motion**, in one of two styles (``motion``):
  ``"absolute"``: a pose to follow while a clutch is held (VR), see pose_input();
  ``"rate"``: velocities while keys or axes are held (keyboard), see rate_input().

Writing a new controller: subclass TeleopDevice, set ``name`` and ``motion``,
implement snapshot() and pose_input() or rate_input() (and stop() if it holds
anything), then use it with make_config(teleop="your_module:YourDevice").
Rate devices get the per-axis locks, the safe start pose and the 7-number
action format for free from RateTeleopPolicy.
"""

import os
import select
import sys
import threading
import time

EVENTS = ("start", "end_trajectory", "save", "discard", "neutral", "end_session", "confirm", "cancel")


class TeleopDevice:
    name = ""
    motion = "absolute"
    # event -> how the operator triggers it, for prompts and the controls card
    LABELS = {}

    def snapshot(self):
        """{event: bool} for every event in EVENTS, from one read of the device."""
        raise NotImplementedError

    def label(self, event):
        return self.LABELS.get(event, event)

    def pose_input(self):
        """Absolute motion: (pose 4x4, trigger_pressed, trigger_amount 0..1, clutch) or None."""
        raise NotImplementedError

    def rate_input(self):
        """Rate motion: (linear m/s [x,y,z], angular rad/s [roll,pitch,yaw], gripper 0 closed..1 open)."""
        raise NotImplementedError

    def reset_trajectory(self):
        """Called before each trajectory (e.g. to reopen a toggled gripper)."""

    def controls_lines(self, control=None):
        """Lines describing this device's controls, for the controls card."""
        return []

    def stop(self):
        """Release the device (threads, files) when collection ends."""


class VRDevice(TeleopDevice):
    """Meta Quest right controller, read with oculus_reader over adb."""

    name = "vr"
    motion = "absolute"
    # The buttons the hand-written VR code used for each step.
    BUTTONS = {
        "start": "RG", "cancel": "RG",          # grip (middle finger)
        "neutral": "B", "end_trajectory": "B",   # B: before / during recording
        "save": "A", "confirm": "A",
        "discard": "RJ", "end_session": "RJ",    # right joystick press: after / before recording
    }
    LABELS = {
        "start": "the grip button", "cancel": "the grip button",
        "neutral": "B", "end_trajectory": "B",
        "save": "A", "confirm": "A",
        "discard": "the right joystick", "end_session": "the right joystick",
    }

    def __init__(self):
        from oculus_reader import OculusReader
        self.reader = OculusReader()

    def raw_buttons(self):
        """The oculus_reader button dict, plus 'handle' (= grip), as VR_WidowX always exposed."""
        _, buttons = self.reader.get_transformations_and_buttons()
        buttons['handle'] = buttons.get('RG', False)
        return buttons

    def snapshot(self):
        buttons = self.raw_buttons()
        return {event: bool(buttons.get(button)) for event, button in self.BUTTONS.items()}

    def pose_input(self):
        poses, buttons = self.reader.get_transformations_and_buttons()
        if poses == {}:
            return None
        return poses['r'], buttons['RTr'], buttons['rightTrig'][0], buttons['RG']

    def stop(self):
        if hasattr(self.reader, 'stop'):
            self.reader.stop()


class KeyboardDevice(TeleopDevice):
    """Keys typed in the collection terminal, with a controls profile (teleop_profiles.py).

    The terminal reports a held key as repeated presses (after a short pause
    for the first one), so a key counts as held for HOLD_S after its last
    press. Session keys (start, save, ...) are single events: each press is
    reported once, so the Enter that starts a trajectory does not also end it.
    Reading starts on first use, after run_data_collection.py's own y/n
    questions.
    """

    name = "keyboard"
    motion = "rate"
    HOLD_S = 0.15
    SESSION_EVENTS = EVENTS

    def __init__(self, profile_path=None):
        from widowx_envs.teleop_profiles import check_profile, load_profile
        self.profile = load_profile(profile_path)
        problems = check_profile(self.profile)
        if problems:
            raise ValueError("invalid controls profile: " + "; ".join(problems))
        self.key_actions = {}
        for action, key in self.profile["bindings"].items():
            self.key_actions.setdefault(key.lower(), []).append(action)
        self.LABELS = {e: self._key_label(self.profile["bindings"][e]) for e in EVENTS}
        self.lock = threading.Lock()
        self.last_press = {}            # motion action -> time of its last key press
        self.pending = set()            # session events pressed since the last snapshot
        self.speed_level = self.profile["start_speed_level"]
        self.gripper = 1.0              # open
        self.thread = None
        self.running = False
        self.saved_tty = None

    @staticmethod
    def _key_label(key):
        return key.upper() if len(key) == 1 and key.isalpha() else key

    # -- terminal ---------------------------------------------------------- #

    def _ensure_started(self):
        if self.thread is not None:
            return
        if not sys.stdin.isatty():
            raise RuntimeError("keyboard teleop needs a terminal: run it with datacollection.py "
                               "(or docker compose exec -it)")
        import termios
        import tty
        fd = sys.stdin.fileno()
        self.saved_tty = termios.tcgetattr(fd)
        tty.setcbreak(fd)  # keys arrive one by one, not echoed; Ctrl+C still works
        self.running = True
        self.thread = threading.Thread(target=self._read_keys, daemon=True)
        self.thread.start()

    def _read_keys(self):
        fd = sys.stdin.fileno()
        buf = ""
        while self.running:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if not ready:
                continue
            buf += os.read(fd, 64).decode(errors="ignore")
            keys, buf = self._parse(buf)
            for key in keys:
                self._on_key(key)

    @staticmethod
    def _parse(buf):
        """Split terminal input into key names; returns (keys, unparsed rest)."""
        arrows = {"\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left"}
        named = {" ": "space", "\n": "enter", "\r": "enter", "\t": "tab", "\x7f": "backspace"}
        keys = []
        while buf:
            if buf.startswith("\x1b"):
                if buf[:3] in arrows:
                    keys.append(arrows[buf[:3]]); buf = buf[3:]; continue
                if len(buf) < 3 and buf in ("\x1b", "\x1b["):
                    if len(buf) == 1:
                        keys.append("esc"); buf = ""
                    break
                keys.append("esc"); buf = buf[1:]; continue
            ch, buf = buf[0], buf[1:]
            keys.append(named.get(ch, ch.lower()))
        return keys, buf

    def _on_key(self, key):
        now = time.time()
        with self.lock:
            for action in self.key_actions.get(key, []):
                if action in self.SESSION_EVENTS:
                    self.pending.add(action)
                elif action == "gripper_toggle":
                    self.gripper = 0.0 if self.gripper > 0.5 else 1.0
                elif action == "gripper_close":
                    self.gripper = max(0.0, self.gripper - self.profile["gripper_step"])
                elif action == "gripper_open":
                    self.gripper = min(1.0, self.gripper + self.profile["gripper_step"])
                elif action in ("faster", "slower"):
                    levels = self.profile["speed_levels"]
                    step = 1 if action == "faster" else -1
                    new = min(len(levels) - 1, max(0, self.speed_level + step))
                    if new == self.speed_level:
                        print("\r[keyboard] already at the {} speed (x{})".format(
                            "highest" if step > 0 else "lowest", levels[new]), flush=True)
                    else:
                        self.speed_level = new
                        print("\r[keyboard] speed x{}".format(levels[new]), flush=True)
                else:
                    self.last_press[action] = now

    # -- device interface --------------------------------------------------- #

    def snapshot(self):
        self._ensure_started()
        with self.lock:
            events = {e: e in self.pending for e in EVENTS}
            self.pending.clear()
        return events

    def rate_input(self):
        self._ensure_started()
        now = time.time()
        with self.lock:
            held = {a for a, t in self.last_press.items() if now - t < self.HOLD_S}
            scale = self.profile["speed_levels"][self.speed_level]
            gripper = self.gripper
        lin_speed = self.profile["linear_speed_m_s"] * scale
        ang_speed = self.profile["angular_speed_deg_s"] * scale * 3.141592653589793 / 180.0

        def axis(name):
            return (name + "+" in held) - (name + "-" in held)

        linear = [axis("x") * lin_speed, axis("y") * lin_speed, axis("z") * lin_speed]
        angular = [axis("roll") * ang_speed, axis("pitch") * ang_speed, axis("yaw") * ang_speed]
        return linear, angular, gripper

    def reset_trajectory(self):
        with self.lock:
            self.gripper = 1.0  # the env opens the gripper at reset
            self.last_press.clear()

    def controls_lines(self, control=None):
        from widowx_envs.teleop_profiles import describe_profile
        return describe_profile(self.profile, control)

    def stop(self):
        self.running = False
        if self.saved_tty is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.saved_tty)
            self.saved_tty = None


DEVICES = {"vr": VRDevice, "keyboard": KeyboardDevice}


def device_class(name):
    """The device class for a teleop name: a built-in one, or "module:Class"."""
    if name in DEVICES:
        return DEVICES[name]
    if isinstance(name, str) and ":" in name:
        import importlib
        module, _, cls = name.partition(":")
        return getattr(importlib.import_module(module), cls)
    raise ValueError("unknown teleop device {!r}: use one of {}, or 'module:Class'".format(
        name, ", ".join(DEVICES)))


def make_device(name, profile_path=None):
    cls = device_class(name)
    if cls is KeyboardDevice:
        return cls(profile_path)
    return cls()
