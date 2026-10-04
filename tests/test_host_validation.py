"""Exercise HOST script safety/failure decisions with fake command/HTTP boundaries.
Never invokes Docker or Kubernetes.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

SOURCE = Path('scripts/final_host_validation.sh').read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]


class HostValidationTests(unittest.TestCase):
    def execute(self, *, unsafe=False, high_cpu=False, zombie=False, kube_failure=False, loki_error=False, shell_form=False, source=SOURCE):
        commands = []
        removed = False
        created = False
        other = {'Id': 'other-id', 'Name': '/MODUI', 'Config': {'Image': 'modui:latest'},
                 'State': {'StartedAt': 'original', 'Status': 'running'}}
        def popen(args, **kwargs):
            nonlocal removed, created
            commands.append(args)
            output, code = '', 0
            if args[:3] == ['docker', 'ps', '-aq']:
                output = 'target-id\nother-id'
            elif args[:2] == ['docker', 'inspect']:
                if args[2] == 'other-id':
                    item = other
                else:
                    item = {'Id': 'new-id' if created else 'target-id', 'Name': '/aiops-final-health',
                            'Config': {'Image': 'modui:latest' if unsafe else 'aiops-engine:1.0.0', 'Labels': None, 'Healthcheck': {'Test': ['CMD-SHELL', 'python'] if shell_form else ['CMD', '/usr/local/bin/aiops-healthcheck']}},
                            'State': {'Running': True, 'Pid': 100, 'Health': {'Status': 'healthy'}},
                            'NetworkSettings': {'Ports': {'8000/tcp': [{'HostPort': '49100'}]}}}
                output = json.dumps([item])
            elif args[:2] == ['docker', 'rm']:
                removed = True
            elif args[:2] == ['docker', 'run']:
                created = True
                output = 'new-id'
            elif args[:2] == ['docker', 'stats']:
                output = json.dumps({'CPUPerc': '594%' if high_cpu else '0.1%', 'PIDs': '3'})
            elif args[:2] == ['docker', 'top']:
                output = 'PID PPID STAT COMMAND\n1 0 S python\n' + ('2 1 Z python\n' if zombie else '')
            elif args[:3] == ['kubectl', 'config', 'current-context']:
                output = 'test-context'
            elif args[:3] == ['kubectl', 'config', 'view']:
                output = json.dumps({'contexts': [{}]})
            elif args[0] == 'kubectl':
                output = json.dumps({'kind': 'PodList', 'items': []})
                code = 1 if kube_failure else 0
            process = Mock(returncode=code)
            process.communicate.return_value = (output, '')
            return process
        response = Mock(status=200)
        response.read.return_value = b'{"status":"ok","mode":"read-only","store":"memory"}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        def open_url(url, **kw):
            if loki_error and ':3300/ready' in url:
                raise urllib.error.HTTPError(url, 503, 'not ready', {},
                                            io.BytesIO(b'Ingester not ready; token=private-example'))
            return response
        opener.open.side_effect = open_url
        output = io.StringIO()
        exit_code = 0
        ticks = 0
        def accounting(_):
            nonlocal ticks
            ticks += 1
            return {'time': ticks * .5, 'cpu_usec': ticks * (2970000 if high_cpu else 500),
                    'pids': 2, 'tasks': {1: {'name': 'docker-init', 'start': '1', 'state': 'Z' if zombie else 'S', 'ticks': 0, 'pid': 1},
                                         2: {'name': 'uvicorn', 'start': '2', 'state': 'S', 'ticks': 0, 'pid': 2}}}
        with patch('scripts.host_runtime.locate_cgroup', return_value='/fake'), \
             patch('scripts.host_runtime.snapshot', side_effect=accounting), \
             patch('subprocess.Popen', side_effect=popen), patch('shutil.which', return_value='/fake/tool'), \
             patch('urllib.request.build_opener', return_value=opener), patch('time.sleep'), \
             contextlib.redirect_stdout(output):
            try:
                exec(compile(source, 'final_host_validation.sh:embedded-python', 'exec'), {})
            except SystemExit as error:
                exit_code = error.code
        return commands, output.getvalue(), exit_code, removed

    def test_success_changes_only_exact_target_and_uses_only_kube_get(self):
        commands, output, code, removed = self.execute()
        self.assertEqual(code, 0)
        self.assertTrue(removed)
        self.assertIn('PASS: overall HOST validation', output)
        self.assertEqual([c for c in commands if c[:2] == ['docker', 'rm']],
                         [['docker', 'rm', '-f', 'target-id']])
        self.assertFalse(any(c[1] in ('stop', 'restart', 'prune') for c in commands if c[0] == 'docker'))
        remote = [c for c in commands if c[0] == 'kubectl' and c[1] != 'config']
        self.assertEqual(len(remote), 1)
        self.assertIn('get', remote[0]); self.assertIn('pods', remote[0])
        self.assertFalse(any(c[:2] == ['docker', 'exec'] for c in commands))

    def test_refuse_unexpected_target_without_mutating_containers(self):
        commands, output, code, removed = self.execute(unsafe=True)
        self.assertEqual(code, 1)
        self.assertFalse(removed)
        self.assertFalse(any(c[:2] == ['docker', 'run'] for c in commands))
        self.assertIn('replacement refused', output)

    def test_high_cpu_is_failure(self):
        _, output, code, _ = self.execute(high_cpu=True)
        self.assertEqual(code, 1)
        self.assertIn('FAIL: idle CPU stability', output)

    def test_repeated_zombies_are_failure(self):
        _, output, code, _ = self.execute(zombie=True)
        self.assertEqual(code, 1)
        self.assertIn('FAIL: repeated zombie/defunct checks', output)

    def test_configured_kubernetes_failure_prevents_overall_pass(self):
        _, output, code, _ = self.execute(kube_failure=True)
        self.assertEqual(code, 2)
        self.assertIn('NOT AVAILABLE: Kubernetes READ-ONLY connectivity', output)
        self.assertNotIn('PASS: overall HOST validation', output)

    def test_loki_503_is_external_incomplete_with_safe_body(self):
        _, output, code, _ = self.execute(loki_error=True)
        self.assertEqual(code, 2)
        self.assertIn('HTTP 503', output)
        self.assertIn('Ingester not ready', output)
        self.assertNotIn('private-example', output)
        self.assertIn('NOT AVAILABLE: overall HOST validation', output)

    def test_actual_shell_and_tee_preserve_script_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / 'python3'
            # The actual bash script supplies stdin; only command/HTTP boundaries are mocked.
            code = ("import sys; from tests.test_host_validation import HostValidationTests; "
                    "r=HostValidationTests().execute(high_cpu=True, source=sys.stdin.read()); "
                    "print(r[1]); sys.exit(r[2])")
            import shlex
            launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote(code) + '\n')
            launcher.chmod(0o755)
            env = dict(os.environ, PATH=directory + ':' + os.environ['PATH'])
            command = ('set -o pipefail; bash scripts/final_host_validation.sh | tee ' +
                       shlex.quote(directory + '/log') +
                       '; codes=("${PIPESTATUS[@]}"); printf "SCRIPT=%s TEE=%s\\n" "${codes[0]}" "${codes[1]}"; exit "${codes[0]}"')
            result = subprocess.run(['bash', '-c', command], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('FAIL: overall HOST validation', result.stdout)
            self.assertIn('SCRIPT=1 TEE=0', result.stdout)

    def test_shell_form_image_fails_before_container_replacement(self):
        commands, output, code, removed = self.execute(shell_form=True)
        self.assertEqual(code, 1)
        self.assertFalse(removed)
        self.assertIn('FAIL: image healthcheck exec form', output)
        self.assertFalse(any(c[:2] == ['docker', 'run'] for c in commands))
