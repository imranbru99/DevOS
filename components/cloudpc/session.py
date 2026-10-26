"""Local reminder state; never infers a remote Cloud PC's connection or activity."""
from dataclasses import dataclass
import time


def clock():
    # Include suspend time so a sleeping laptop cannot leave a stale countdown.
    if hasattr(time, 'CLOCK_BOOTTIME'):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    return time.monotonic()


@dataclass
class Reminder:
    limit: int = 600
    lead: int = 120
    started: float | None = None
    warned: bool = False
    expired: bool = False

    def __post_init__(self):
        if not 60 <= self.limit <= 7200 or not 0 < self.lead < self.limit:
            raise ValueError('Reminder lead must be shorter than the 1–120 minute limit.')

    def start(self, now):
        self.started = now
        self.warned = self.expired = False

    def pause(self):
        self.started = None
        self.warned = self.expired = False

    def remaining(self, now):
        if self.started is None:
            return self.limit
        return max(0, self.limit - max(0, int(now - self.started)))

    def tick(self, now):
        if self.started is None or self.expired:
            return None
        remaining = self.remaining(now)
        if remaining == 0:
            self.expired = self.warned = True
            return 'expired'
        if remaining <= self.lead and not self.warned:
            self.warned = True
            return 'warning'
        return None
