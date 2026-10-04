"""Thread-safe bounded in-memory store. One worker; no persistence guarantee."""
from collections import OrderedDict
from copy import deepcopy
import threading

class IncidentStore:
    def __init__(self, capacity=1000):
        if type(capacity) is not int or not 1 <= capacity <= 10000:
            raise ValueError('Invalid store capacity')
        self.capacity = capacity
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def add_all(self, incidents):
        with self._lock:
            for incident in incidents:
                self._items[incident.incident_id] = incident.to_dict()
                while len(self._items) > self.capacity:
                    self._items.popitem(last=False)

    def list(self, limit=100):
        with self._lock:
            return deepcopy(list(self._items.values())[-limit:])

    def get(self, incident_id):
        with self._lock:
            return deepcopy(self._items.get(incident_id))
