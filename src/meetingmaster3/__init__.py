"""MeetingMaster3: local-first meeting intelligence."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("meetingmaster3")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
