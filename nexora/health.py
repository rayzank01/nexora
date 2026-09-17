"""Worker progress separate from HTTP liveness; safe to expose without credentials."""
import threading
import time


class WorkerHealth:
    def __init__(self, max_age=90, clock=time.monotonic):
        self.max_age = max_age
        self.clock = clock
        self.lock = threading.Lock()
        self.last_poll = None
        self.last_scheduler = None

    def poll_ok(self):
        with self.lock:
            self.last_poll = self.clock()

    def scheduler_ok(self):
        with self.lock:
            self.last_scheduler = self.clock()

    def snapshot(self):
        with self.lock:
            now = self.clock()
            checks = {name: value is not None and 0 <= now - value <= self.max_age
                      for name, value in [('polling', self.last_poll), ('scheduler', self.last_scheduler)]}
        ready = all(checks.values())
        return ready, {'status': 'ready' if ready else 'not_ready', 'checks': checks}
