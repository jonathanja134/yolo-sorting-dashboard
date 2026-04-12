import time

class HealthMonitor:
    def __init__(self):
        self.last_frame_time = time.time()
        self.errors = 0

    def frame_ok(self):
        self.last_frame_time = time.time()

    def error(self):
        self.errors += 1

    def is_alive(self):
        return time.time() - self.last_frame_time < 2
