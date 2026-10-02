"""Runner observation errors shared by the direct transport and Sandbox Service client."""

class RunnerError(Exception):
    """The runner ended the stream with an error."""


class OpenTimeoutError(RunnerError):
    """The runner accepted Attach but did not answer Open in time: wedged, or a half-open connection."""


class StreamClosedError(Exception):
    """The runner ended the stream without an error, after StopRunnerSession or Detach."""
