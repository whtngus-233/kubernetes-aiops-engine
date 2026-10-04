"""Offline integration: real engine, normalization, correlation, API and store.
Only the external Kubernetes acquisition boundary is replaced by a fixture.
"""
from unittest.mock import Mock
from app.api import create_app
from app.config import Settings
from app.engine import AnalysisEngine
from app.collectors.prometheus import PrometheusCollector
from app.collectors.loki import LokiCollector
from app.analyzers.llm import LLMAnalyzer
from tests.async_support import AsyncAPITestCase, async_client
from tests.test_platform import fixture


class PipelineIntegrationTests(AsyncAPITestCase):
    async def test_analyze_store_retrieve_and_disabled_integrations(self):
        collector = Mock(); collector.collect.return_value = fixture()
        engine = AnalysisEngine(Settings(allowed_namespaces=('demo',)), collector_factory=lambda: collector)
        async with async_client(create_app(engine.settings, engine=engine)) as client:
            self.assertEqual((await client.get('/health')).status_code, 200)
            response = await client.post('/api/analyze', json={'namespace': 'demo'})
            self.assertEqual(response.status_code, 200)
            report = response.json()['incidents'][0]
            self.assertEqual(report['category'], 'DEPENDENCY_CONNECTION_FAILURE')
            self.assertFalse(report['automatic_action_taken'])
            self.assertIsNone(report['llm_analysis'])
            stored = (await client.get('/api/incidents/' + report['incident_id'])).json()
            self.assertEqual(stored, report)
            self.assertEqual(len((await client.get('/api/incidents')).json()['incidents']), 1)
        collector.close.assert_called_once()

    async def test_all_optional_sources_fail_preserve_kubernetes_rules(self):
        collector = Mock(); collector.collect.return_value = fixture('01_crashloop')
        transport = Mock(); transport.request.side_effect = TimeoutError('private-detail')
        provider = Mock(); provider.analyze.side_effect = ValueError('private-detail')
        engine = AnalysisEngine(Settings(allowed_namespaces=('demo',)), collector_factory=lambda: collector,
                                prometheus=PrometheusCollector('http://metrics', transport=transport),
                                loki=LokiCollector('http://logs', transport=transport), llm=LLMAnalyzer(provider))
        async with async_client(create_app(engine.settings, engine=engine)) as client:
            response = await client.post('/api/analyze', json={'namespace': 'demo'})
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertTrue(result['warnings'])
            self.assertEqual(result['incidents'][0]['category'], 'CrashLoopBackOff')
            self.assertEqual(result['incidents'][0]['confidence'], 'low')
            self.assertEqual(result['incidents'][0]['llm_analysis']['status'], 'unavailable')
            self.assertNotIn('private-detail', response.text)
