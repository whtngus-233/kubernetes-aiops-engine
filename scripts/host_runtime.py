"""HOST cgroup-v2 observation; never runs a process inside the container.

Fail closed if raw accounting is inaccessible. Averages use cumulative CPU time
and monotonic wall time, rather than Docker CLI's unrelated instantaneous window.
"""
from pathlib import Path
import os
import time


def locate_cgroup(pid):
    for line in Path(f'/proc/{pid}/cgroup').read_text().splitlines():
        if line.startswith('0::'):
            relative = line[3:].lstrip('/')
            root = Path('/sys/fs/cgroup').resolve()
            path = (root / relative).resolve()
            if path != root and root in path.parents and (path / 'cpu.stat').is_file():
                return path
    raise RuntimeError('HOST cgroup-v2 accounting unavailable; stability evidence incomplete')


def snapshot(cgroup):
    start = time.monotonic()
    cpu = dict(line.split() for line in (cgroup / 'cpu.stat').read_text().splitlines())
    tasks = {}
    for pid in (cgroup / 'cgroup.procs').read_text().split():
        try:
            directories = list(Path(f'/proc/{pid}/task').iterdir())
        except FileNotFoundError:
            continue  # A transient probe exited during observation.
        executable = ''
        try:
            executable = os.readlink(f'/proc/{pid}/exe')
        except (PermissionError, FileNotFoundError):
            pass
        for task in directories:
            try:
                raw = (task / 'stat').read_text()
                end = raw.rfind(')')
                fields = raw[end+2:].split()
                tasks[int(task.name)] = {'pid': int(pid), 'name': raw[raw.find('(')+1:end],
                                        'executable': executable, 'state': fields[0], 'start': fields[19],
                                        'ticks': int(fields[11]) + int(fields[12])}
            except FileNotFoundError:
                continue
    return {'time': start, 'wall_time': time.time(), 'cpu_usec': int(cpu['usage_usec']),
            'pids': int((cgroup / 'pids.current').read_text()), 'tasks': tasks}


def interval_cpu(previous, current):
    elapsed = current['time'] - previous['time']
    delta = current['cpu_usec'] - previous['cpu_usec']
    if elapsed <= 0 or delta < 0:
        raise RuntimeError('invalid cumulative CPU interval')
    return delta / (elapsed * 10000)


def lifecycle(baseline, current, first_seen=None):
    original = baseline['tasks']
    tasks = current['tasks']
    missing = [tid for tid, task in original.items()
               if tid not in tasks or tasks[tid]['start'] != task['start']]
    extras = {tid: task for tid, task in tasks.items() if tid not in original}
    def recognized(task):
        # Native probe is single-threaded. runc's Go init may have multiple tasks
        # before exec; require both the runtime comm and executable identity.
        if task['name'] == 'aiops-healthche':
            return True
        executable = Path(task.get('executable', '').removesuffix(' (deleted)')).name
        return task['name'] == 'runc:[2:INIT]' and executable in ('runc', 'docker-runc')
    unexpected = {tid: task for tid, task in extras.items() if not recognized(task)}
    groups = {task.get('pid', tid) for tid, task in extras.items()}
    native = sum(task['name'] == 'aiops-healthche' for task in extras.values())
    expired = False
    if first_seen is not None:
        identities = {(task.get('pid', tid), task['start']) for tid, task in extras.items()}
        for identity in list(first_seen):
            if identity not in identities:
                del first_seen[identity]
        for identity in identities:
            first_seen.setdefault(identity, current['time'])
            expired |= current['time'] - first_seen[identity] >= 3
    # Keep the former absolute ceiling; only evidenced runtime threads are exempt
    # from the incorrect range limit. Never accept an unexplained PIDS excess.
    accounted_bound = len(original) + max(1, len(extras))
    ok = (not missing and not unexpected and len(groups) <= 1 and native <= 1 and not expired
          and current['pids'] <= min(32, accounted_bound))
    return ok, extras


def cpu_sources(previous, current, ticks_per_second):
    elapsed = current['time'] - previous['time']
    by_task = {}
    for tid, task in current['tasks'].items():
        old = previous['tasks'].get(tid)
        if old and old['start'] == task['start']:
            by_task[tid] = {'name': task['name'],
                            'cpu_percent': 100 * (task['ticks'] - old['ticks']) / (ticks_per_second * elapsed)}
    return {'cgroup_cpu_percent': interval_cpu(previous, current), 'surviving_task_cpu': by_task}
