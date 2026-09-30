"""Frame subscriptions — in-process copies of the Relay's input Frames.

A **Frame** is one complete, CRC-valid RTCM 3 message as delimited by
the Relay.  A **Frame subscriber** receives a copy of every Frame the
Relay reads from its input, before any destination filtering.  It is
not a destination and never affects relaying: its queue is bounded and
drops Frames when full, so a slow subscriber can never block the hub.
The Relay never decodes a Frame's payload (ADR 0003).
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass

#: Default per-subscriber queue size, comparable to destination queues.
DEFAULT_FRAME_QUEUE_SIZE = 100


@dataclass(frozen=True)
class Frame:
    """One complete, CRC-valid RTCM 3 message, exactly as read from the input.

    Attributes:
        message_id: The RTCM message number (e.g. 1005, 1074).
        data: The whole frame: header, payload and CRC.
    """

    message_id: int
    data: bytes


class FrameSubscription:
    """A subscription to the Frames one engine run reads from its input.

    Obtained from :meth:`RelayEngine.subscribe_frames`.  Read Frames with
    :meth:`get_frame`, iteration or :meth:`drain`; call :meth:`close`
    when done.  The subscription also ends when the engine stops: Frames
    already queued can still be read, after which reads report closed.
    """

    def __init__(
        self,
        message_ids: frozenset[int] | None = None,
        maxsize: int = DEFAULT_FRAME_QUEUE_SIZE,
        on_close: Callable[[FrameSubscription], None] | None = None,
    ) -> None:
        self._message_ids = message_ids
        self._on_close = on_close
        self._queue: queue.Queue[Frame | None] = queue.Queue(maxsize=maxsize)
        self._closed = threading.Event()
        self._dropped = 0

    @property
    def message_ids(self) -> frozenset[int] | None:
        """The message IDs this subscription wants, or ``None`` for all."""
        return self._message_ids

    @property
    def closed(self) -> bool:
        """``True`` once closed by the subscriber or by the engine stopping."""
        return self._closed.is_set()

    @property
    def dropped(self) -> int:
        """Frames dropped because this subscription's queue was full."""
        return self._dropped

    def offer(self, frame: Frame) -> bool:
        """Hand a Frame to this subscription without ever blocking.

        Called by the hub.  Returns ``False`` if the Frame was not queued
        because the subscription is closed, filtered it out, or is full
        (the last case is counted in :attr:`dropped`).
        """
        if self._closed.is_set():
            return False
        if self._message_ids is not None and frame.message_id not in self._message_ids:
            return False
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            self._dropped += 1
            return False
        return True

    def get_frame(self, timeout: float | None = None) -> Frame | None:
        """Return the next Frame, or ``None`` on timeout or once closed and empty."""
        if self._closed.is_set():
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return None
            return item
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        return item

    def drain(self, max_frames: int | None = None) -> list[Frame]:
        """Return the Frames queued right now, without waiting.

        Args:
            max_frames: Return at most this many; ``None`` for all queued.
        """
        frames: list[Frame] = []
        while max_frames is None or len(frames) < max_frames:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                frames.append(item)
        return frames

    def __iter__(self) -> Iterator[Frame]:
        """Yield Frames as they arrive, until the subscription is closed."""
        while True:
            frame = self.get_frame(timeout=0.5)
            if frame is not None:
                yield frame
            elif self._closed.is_set():
                return

    def close(self) -> None:
        """End the subscription.  Safe to call more than once."""
        if self._closed.is_set():
            return
        self._closed.set()
        if self._on_close is not None:
            self._on_close(self)
        # Wake a reader blocked in get_frame(); if the queue is full the
        # reader isn't blocked, so a missing wake-up is harmless.
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
