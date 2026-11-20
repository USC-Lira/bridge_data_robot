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
  ``"absolute"``: a pose to follow while a clutch is held (VR);
  ``"rate"``: velocities while keys or axes are held (keyboard, SpaceMouse).
"""

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


DEVICES = {"vr": VRDevice}


def make_device(name):
    if name not in DEVICES:
        raise ValueError("unknown teleop device {!r}: use one of {}".format(name, ", ".join(DEVICES)))
    return DEVICES[name]()
