import unittest
from scripts.host_runtime import interval_cpu, lifecycle


class RuntimeAccountingTests(unittest.TestCase):
    def task(self, name, start='1'):
        return {'name': name, 'start': start}

    def test_cpu_uses_elapsed_time_and_cumulative_accounting(self):
        self.assertAlmostEqual(interval_cpu({'time': 10, 'cpu_usec': 100},
                                           {'time': 15, 'cpu_usec': 250100}), 5)
        with self.assertRaises(RuntimeError):
            interval_cpu({'time': 10, 'cpu_usec': 100}, {'time': 10, 'cpu_usec': 100})

    def test_probe_is_transient_but_unknown_threads_and_pid_reuse_fail(self):
        baseline = {'tasks': {1: self.task('docker-init'), 2: self.task('uvicorn')}}
        for extra, count, expected in (({}, 2, True), ({3: self.task('aiops-healthche')}, 3, True),
                                      ({3: self.task('python')}, 3, False),
                                      ({3: self.task('aiops-healthche'), 4: self.task('aiops-healthche')}, 4, False),
                                      ({}, 7, False)):
            with self.subTest(extra=extra, count=count):
                current = {'tasks': baseline['tasks'] | extra, 'pids': count}
                self.assertEqual(lifecycle(baseline, current)[0], expected)
        self.assertFalse(lifecycle(baseline, {'tasks': {1: self.task('docker-init'),
                               2: self.task('uvicorn', 'new')}, 'pids': 2})[0])

    def test_runtime_threads_require_identity_and_bounded_lifetime(self):
        baseline = {'tasks': {1: self.task('docker-init'), 2: self.task('uvicorn')}}
        extras = {tid: {'name': 'runc:[2:INIT]', 'start': str(tid), 'pid': 3,
                        'executable': '/usr/bin/runc'} for tid in range(3, 8)}
        current = {'time': 10, 'tasks': baseline['tasks'] | extras, 'pids': 7}
        seen = {}
        self.assertTrue(lifecycle(baseline, current, seen)[0])
        current['time'] = 13
        self.assertFalse(lifecycle(baseline, current, seen)[0])
        current['time'] = 10
        extras[3]['executable'] = '/usr/bin/python'
        self.assertFalse(lifecycle(baseline, current, {})[0])
        clean = {'time': 14, 'tasks': baseline['tasks'], 'pids': 2}
        self.assertTrue(lifecycle(baseline, clean, seen)[0])
        self.assertEqual(seen, {})
