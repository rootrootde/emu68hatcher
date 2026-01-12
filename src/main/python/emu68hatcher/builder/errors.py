"""build error types for Emu68 Hatcher"""


class BuildError(Exception):
    """raised when a build error occurs"""

    pass


class BuildCancelledError(Exception):
    """raised when build is cancelled"""

    pass
