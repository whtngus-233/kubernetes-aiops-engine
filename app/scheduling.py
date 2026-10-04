"""Explicit bounded scheduling; never starts on import or API startup."""
import argparse
import math
import signal
import threading
import time


def scheduled_analysis(engine, namespace, iterations=1, interval_seconds=60, stop_event=None):
    if (type(iterations) is not int or not 1 <= iterations <= 1000
            or isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (int, float))
            or not math.isfinite(interval_seconds) or interval_seconds < 30):
        raise ValueError('Invalid schedule bounds')
    for index in range(iterations):
        if stop_event and stop_event.is_set():
            break
        try:
            result = engine.analyze(namespace)
        except Exception:
            # Never expose backend exception text or terminate later iterations.
            result = ([], ['scheduler: analysis unavailable'])
        yield result
        if index + 1 < iterations:
            if stop_event:
                if stop_event.wait(interval_seconds):
                    break
            else:
                time.sleep(interval_seconds)


def main(argv=None):
    from app.config import Settings
    from app.engine import AnalysisEngine
    from app.report import render_structured
    parser = argparse.ArgumentParser(description='Bounded READ-ONLY analysis scheduler')
    parser.add_argument('--namespace', default='default')
    parser.add_argument('--iterations', type=int, default=1)
    parser.add_argument('--interval', type=float, default=60)
    args = parser.parse_args(argv)
    stop = threading.Event()
    previous = {}
    try:
        for name in (signal.SIGINT, signal.SIGTERM):
            previous[name] = signal.signal(name, lambda *_: stop.set())
        engine = AnalysisEngine(Settings.from_env())
        status = 0
        for incidents, warnings in scheduled_analysis(engine, args.namespace, args.iterations, args.interval, stop):
            print(render_structured(incidents, warnings), flush=True)
            if warnings:
                status = 2
        return status
    except ValueError:
        parser.error('Invalid settings or schedule bounds (iterations 1–1000, interval >=30 seconds)')
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)


if __name__ == '__main__':
    raise SystemExit(main())
