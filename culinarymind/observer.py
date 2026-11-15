"""OBSERVER pattern. Subject = models, Observer = GUI views / CLI listeners."""
from abc import ABC, abstractmethod

class Observer(ABC):
    @abstractmethod
    def update(self, subject, event: str, payload=None): ...

class Subject:
    def __init__(self):
        self._observers = []
    def attach(self, o: Observer):
        if o not in self._observers:
            self._observers.append(o)
    def detach(self, o: Observer):
        self._observers.remove(o)
    def notify_observers(self, event: str, payload=None):
        for o in list(self._observers):
            o.update(self, event, payload)
