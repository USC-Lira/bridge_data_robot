class Bad_Traj_Exception(Exception):
    def __init__(self):
        pass


class Image_Exception(Exception):
    def __init__(self):
        pass


class Environment_Exception(Exception):
    def __init__(self):
        pass


class SessionEnd(Exception):
    """LIRA: the operator ended the collection session from the headset.

    Raised between trajectories (while waiting for the next one), so nothing
    is half-recorded. Not an Environment_Exception on purpose: the control
    loop retries those, and this must reach TrajectoryCollector.run.
    """
    pass
