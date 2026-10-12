"""EventBus para o SSE: cada assinante tem sua fila; quem está lento perde eventos, não trava o poller."""

from __future__ import annotations

import queue
import threading


class EventBus:
    def __init__(self, maxsize: int = 100):
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self.maxsize = maxsize

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(self.maxsize)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def publish(self, event: str, data) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:
                try:  # descarta o mais antigo e tenta de novo
                    q.get_nowait()
                    q.put_nowait((event, data))
                except (queue.Empty, queue.Full):
                    pass

    @property
    def subscribers(self) -> int:
        with self._lock:
            return len(self._subs)
