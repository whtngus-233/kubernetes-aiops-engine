"""Engineering regression checks for safety boundaries and failure isolation."""
import contextlib
import io
import os
import threading
import unittest
from unittest.mock import Mock, patch
from app.config import Settings
from app.engine import AnalysisEngine
from app.main import main
from app.models import Snapshot, CollectionResult
from app.scheduling import scheduled_analysis
from tests.test_platform import fixture


def engine(**kwargs):
    metrics = Mock(); metrics.collect.return_value = CollectionResult()
    logs = Mock(); logs.collect.return_value = CollectionResult()
    return AnalysisEngine(Settings(allowed_namespaces=('demo',)), prometheus=metrics, loki=logs, **kwargs)


class FailureTests(unittest.TestCase):
    def test_empty_evidence(self):
        reports, warnings = engine().analyze_snapshot(Snapshot('demo', []))
        self.assertEqual((reports, warnings), ([], []))

    def test_snapshot_reuse_does_not_accumulate_evidence(self):
        snapshot = fixture()
        analyzer = engine()
        before = len(snapshot.evidence)
        first, _ = analyzer.analyze_snapshot(snapshot)
        second, _ = analyzer.analyze_snapshot(snapshot)
        self.assertEqual(len(snapshot.evidence), before)
        self.assertEqual(first[0].evidence, second[0].evidence)

    def test_conflicting_or_stale_evidence_keeps_uncertainty(self):
        snapshot = fixture('04_high_cpu')
        snapshot.evidence[-1].value = 2  # contradict zero-restart condition
        self.assertFalse(engine().analyze_snapshot(snapshot)[0])

    def test_scheduler_invalid_bounds(self):
        for kwargs in ({'iterations': True}, {'iterations': 1.5}, {'iterations': '2'},
                       {'iterations': 1001}, {'interval_seconds': 29},
                       {'interval_seconds': float('nan')}, {'interval_seconds': float('inf')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                list(scheduled_analysis(Mock(), 'demo', **kwargs))

    def test_scheduler_cancellation_before_and_between_iterations(self):
        stop = threading.Event(); stop.set(); worker = Mock()
        self.assertEqual(list(scheduled_analysis(worker, 'demo', stop_event=stop)), [])
        worker.analyze.assert_not_called()
        stop.clear()
        def analyze(_):
            stop.set()
            return [], []
        worker.analyze.side_effect = analyze
        self.assertEqual(list(scheduled_analysis(worker, 'demo', iterations=2, stop_event=stop)), [([], [])])
        worker.analyze.assert_called_once()

    def test_scheduler_failure_is_sanitized_and_recovers(self):
        worker = Mock(); worker.analyze.side_effect = [TimeoutError('private-value'), ([], [])]
        with patch('app.scheduling.time.sleep'):
            results = list(scheduled_analysis(worker, 'demo', iterations=2))
        self.assertNotIn('private-value', str(results))
        self.assertEqual(results[-1], ([], []))

    def test_engine_prevents_overlapping_execution_and_releases_lock(self):
        analyzer = engine()
        with analyzer._exclusive():
            with self.assertRaises(RuntimeError):
                analyzer.analyze_snapshot(fixture())
        self.assertTrue(analyzer.analyze_snapshot(fixture())[0])

    def test_cli_allowlist_rejected_before_client_creation(self):
        with patch.dict(os.environ, {'AIOPS_ALLOWED_NAMESPACES': 'demo'}), \
             patch('app.main.KubernetesCollector') as collector, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--namespace', 'other', '--structured']), 1)
            collector.assert_not_called()

    def test_structured_cli_partial_failure_exit_status(self):
        collector = Mock(); collector.collect.return_value = Snapshot('demo', [])
        analyzer = Mock(); analyzer.analyze_snapshot.return_value = ([], ['prometheus: unavailable'])
        with patch.dict(os.environ, {'AIOPS_ALLOWED_NAMESPACES': 'demo'}), \
             patch('app.main.KubernetesCollector', return_value=collector), \
             patch('app.main.AnalysisEngine', return_value=analyzer), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--namespace', 'demo', '--format', 'json']), 2)
        collector.close.assert_called_once()

    def test_llm_invalid_json_and_unexpected_response_keep_rules(self):
        from app.analyzers.llm import OpenAIProvider, LLMAnalyzer
        for response in ({'status': 'completed', 'output': [{'type':'message','content':[{'type':'output_text','text':'invalid JSON'}]}]},
                         {'status':'completed','output':None}, {'status':'completed','output':[]}):
            transport = Mock(); transport.request.return_value = response
            advisory = LLMAnalyzer(OpenAIProvider(model='test-model', transport=transport))
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-unit-value'}):
                reports, _ = engine(llm=advisory).analyze_snapshot(fixture())
            self.assertEqual(reports[0].category, 'DEPENDENCY_CONNECTION_FAILURE')
            self.assertEqual(reports[0].llm_analysis['status'], 'unavailable')
