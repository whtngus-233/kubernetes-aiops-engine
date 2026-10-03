"""Explicit bounded schedule. Never runs automatically on import or API startup."""
import time

def scheduled_analysis(engine, namespace, iterations=1, interval_seconds=60, stop_event=None):
    if isinstance(iterations, bool) or not 1 <= iterations <= 1000 or interval_seconds < 30:
        raise ValueError('Invalid schedule bounds')
    for index in range(iterations):
        if stop_event and stop_event.is_set():
            break
        yield engine.analyze(namespace)
        if index + 1 < iterations:
            if stop_event:
                if stop_event.wait(interval_seconds):
                    break
            else:
                time.sleep(interval_seconds)
