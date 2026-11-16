"""备份独占窗口；请求和后台作业共享可重入的读租约。"""
import threading
from contextlib import contextmanager
from functools import wraps


class MaintenanceGate:
    def __init__(self):
        self.condition = threading.Condition(threading.RLock())
        self.local = threading.local()
        self.readers = 0
        self.writer = False
        self.waiting = 0

    @contextmanager
    def activity(self):
        nested = getattr(self.local, 'depth', 0)
        if not nested:
            with self.condition:
                while self.writer or self.waiting:
                    self.condition.wait()
                self.readers += 1
        self.local.depth = nested + 1
        try:
            yield
        finally:
            self.local.depth -= 1
            if not nested:
                with self.condition:
                    self.readers -= 1
                    self.condition.notify_all()

    @contextmanager
    def exclusive(self):
        with self.condition:
            self.waiting += 1
            try:
                while self.writer or self.readers:
                    self.condition.wait()
                self.writer = True
            finally:
                self.waiting -= 1
        try:
            yield
        finally:
            with self.condition:
                self.writer = False
                self.condition.notify_all()


gate = MaintenanceGate()


def coordinated(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with gate.activity():
            return func(*args, **kwargs)
    return wrapped
