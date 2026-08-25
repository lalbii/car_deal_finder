import signal
from contextlib import contextmanager
from types import FrameType
from typing import Iterator


class ShutdownRequested(BaseException):
    pass


@contextmanager
def graceful_shutdown_signals() -> Iterator[None]:
    previous_handlers: dict[signal.Signals, signal.Handlers] = {}

    def request_shutdown(signum: int, frame: FrameType | None) -> None:
        raise ShutdownRequested(signal.Signals(signum).name)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_shutdown)

    try:
        yield
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
