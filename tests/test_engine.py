"""Unittest-compatible tests, discoverable by pytest; no cluster access."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from kubernetes import client as k
from app.collectors.kubernetes import KubernetesCollector, CollectionError
from app.analyzers.rules import RuleEngine
from app.models import PodEvidence, Snapshot, ContainerEvidence
from app.report import render_report
from app.main import main


def pod(reason=None, phase='Running', restarts=0, kind='regular', exit_code=None):
    return PodEvidence('demo', 'test', 'uid1', phase, [ContainerEvidence(
        'app', kind, 'waiting' if reason else 'terminated' if exit_code is not None else 'running',
        restarts, waiting_reason=reason, exit_code=exit_code)])


def page(items, token=None):
    return NS(items=items, metadata=NS(_continue=token))


class EngineTests(unittest.TestCase):
    def test_healthy_and_completed(self):
        self.assertEqual(RuleEngine().analyze(Snapshot('test', [pod(), pod(phase='Succeeded', exit_code=0)])), [])

    def test_reasons(self):
        for reason in ['CrashLoopBackOff', 'ImagePullBackOff', 'ErrImagePull', 'Error', 'OOMKilled']:
            with self.subTest(reason=reason):
                self.assertEqual(RuleEngine().analyze(Snapshot('test', [pod(reason)]))[0].category, reason)

    def test_phase(self):
        for phase in ['Pending', 'Failed']:
            with self.subTest(phase=phase):
                self.assertEqual(RuleEngine().analyze(Snapshot('test', [pod(phase=phase)]))[0].category, phase)

    def test_restart_boundary_and_history(self):
        p = pod(restarts=4)
        self.assertEqual(RuleEngine(5).analyze(Snapshot('test', [p])), [])
        p.containers[0].restart_count = 5
        p.containers[0].previous_terminated_reason = 'Error'
        self.assertEqual([i.category for i in RuleEngine(5).analyze(Snapshot('test', [p]))], ['HighRestartCount'])

    def test_nonzero_exit_and_init(self):
        self.assertEqual(RuleEngine().analyze(Snapshot('test', [pod(kind='init', exit_code=2)]))[0].category, 'Error')

    def test_bad_threshold(self):
        for value in [0, -1, True, '5', 2.5]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                RuleEngine(value)

    def test_collector_pagination_events_states(self):
        state = k.V1ContainerState(waiting=k.V1ContainerStateWaiting(reason='CrashLoopBackOff'))
        last = k.V1ContainerState(terminated=k.V1ContainerStateTerminated(exit_code=1, reason='Error'))
        status = k.V1ContainerStatus(name='app', image='demo', image_id='', ready=False,
                                    restart_count=6, state=state, last_state=last)
        raw = k.V1Pod(metadata=k.V1ObjectMeta(name='demo', namespace='test', uid='uid1'),
                      status=k.V1PodStatus(phase='Running', container_statuses=[status],
                                          init_container_statuses=[status], ephemeral_container_statuses=[status]))
        def event(uid):
            return k.CoreV1Event(metadata=k.V1ObjectMeta(), involved_object=k.V1ObjectReference(uid=uid),
                                 reason='BackOff', message='restart delay', type='Warning', count=2)
        api = Mock(spec=['list_namespaced_pod', 'list_namespaced_event'])
        api.list_namespaced_pod.side_effect = [page([raw], 'next'), page([])]
        api.list_namespaced_event.side_effect = [page([event('uid1')], 'e-next'), page([event('old-uid')])]
        result = KubernetesCollector(api).collect('test')
        self.assertEqual(len(result.pods), 1)
        self.assertEqual(len(result.pods[0].containers), 3)
        self.assertEqual(result.pods[0].containers[0].previous_terminated_reason, 'Error')
        self.assertEqual(len(result.pods[0].events), 1)
        self.assertEqual(api.list_namespaced_pod.call_args.kwargs['_continue'], 'next')
        self.assertEqual(api.list_namespaced_event.call_args.kwargs['_continue'], 'e-next')
        self.assertEqual(api.list_namespaced_event.call_args.kwargs['field_selector'], 'involvedObject.kind=Pod')
        self.assertEqual({call[0] for call in api.method_calls}, {'list_namespaced_pod', 'list_namespaced_event'})

    def test_empty_status(self):
        raw = k.V1Pod(metadata=k.V1ObjectMeta(name='new', namespace='test', uid='x'), status=k.V1PodStatus(phase='Pending'))
        api = Mock()
        api.list_namespaced_pod.return_value = page([raw])
        api.list_namespaced_event.return_value = page([])
        self.assertEqual(KubernetesCollector(api).collect('test').pods[0].containers, [])

    def test_event_failure_and_pod_failure(self):
        api = Mock()
        api.list_namespaced_pod.return_value = page([])
        api.list_namespaced_event.side_effect = RuntimeError('sensitive error')
        result = KubernetesCollector(api).collect('test')
        self.assertTrue(result.warnings)
        self.assertNotIn('sensitive', result.warnings[0])
        api.list_namespaced_pod.side_effect = RuntimeError('secret')
        with self.assertRaisesRegex(CollectionError, 'Pod 조회 실패'):
            KubernetesCollector(api).collect('test')

    def test_report_control_sequences(self):
        p = pod('CrashLoopBackOff')
        p.name = 'bad\x1b[31m\nname'
        snapshot = Snapshot('test', [p])
        report = render_report(snapshot, RuleEngine().analyze(snapshot))
        self.assertNotIn('\x1b', report)
        self.assertIn('CrashLoopBackOff', report)
        self.assertIn('관련 Events: 없음', report)

    def test_cli_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'bad.yaml'
            for content in ['restart_threshold: false', '- invalid', 'namespace: ""', 'unknown: 1']:
                config.write_text(content)
                with self.subTest(content=content), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['--config', str(config)]), 1)

    def test_cli_success_partial_and_close(self):
        api = Mock()
        snapshot = Snapshot('test', [pod()])
        api.collect.return_value = snapshot
        with patch.dict(os.environ, {'AIOPS_ALLOWED_NAMESPACES': 'test'}), patch('app.main.KubernetesCollector', return_value=api), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--namespace', 'test']), 0)
            self.assertIn('Pods: 1', output.getvalue())
            api.close.assert_called_once()
            snapshot.warnings.append('Event 조회 실패')
            self.assertEqual(main(['--namespace', 'test']), 2)

    def test_kubeconfig_failure_is_sanitized(self):
        with patch('app.collectors.kubernetes.config.new_client_from_config', side_effect=RuntimeError('secret')):
            with self.assertRaisesRegex(CollectionError, 'kubeconfig 로드 실패'):
                KubernetesCollector()

    def test_cli_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.yaml'
            config.write_text('namespace: old\nrestart_threshold: 10\ncontext: old-context')
            api = Mock()
            api.collect.return_value = Snapshot('new', [])
            with patch.dict(os.environ, {'AIOPS_ALLOWED_NAMESPACES': 'new'}), patch('app.main.KubernetesCollector', return_value=api) as constructor, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--config', str(config), '--namespace', 'new', '--context', 'new-context', '--restart-threshold', '2']), 0)
                constructor.assert_called_once_with(context='new-context')
                api.collect.assert_called_once_with('new')


if __name__ == '__main__':
    unittest.main()
