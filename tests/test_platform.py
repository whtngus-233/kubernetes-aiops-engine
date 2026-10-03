"""All external dependencies mocked. No live credentials, cluster or traffic."""
import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from app.models import CollectionResult, Snapshot, PodEvidence, ContainerEvidence, IncidentEvidence, utc_now
from app.collectors.prometheus import PrometheusCollector, QUERIES
from app.collectors.loki import LokiCollector
from app.analyzers.correlation import CorrelationEngine
from app.analyzers.llm import LLMAnalyzer, DisabledProvider, OpenAIProvider
from app.notifiers.discord import DiscordNotifier
from app.config import Settings
from app.api import create_app
from app.engine import AnalysisEngine
from app.store import IncidentStore
from app.scheduling import scheduled_analysis
from app.security import sanitize
from app.http import HTTPTransport
from app.collectors.kubernetes import KubernetesCollector, CollectionError
from examples.demo_incidents import load_fixture, FIXTURES


def fixture(name='05_db_connection_refused'):
    return load_fixture(FIXTURES / (name+'.json'))[0]


def incident():
    return CorrelationEngine().analyze(fixture())[0]


def prometheus(rows=None):
    return {'status': 'success', 'data': {'resultType': 'vector', 'result': rows or []}}


def sample(container='app', value='1.2', namespace='demo', pod='demo-app'):
    return {'metric': {'namespace': namespace, 'pod': pod, 'container': container},
            'value': [datetime.now(timezone.utc).timestamp(), value]}


def loki(lines=None, labels=None):
    values = [[str(int(datetime.now(timezone.utc).timestamp()*1e9)), line] for line in (lines or [])]
    return {'status':'success', 'data':{'resultType':'streams', 'result':[
        {'stream': labels or {'namespace':'demo','pod':'demo-app','container':'app'}, 'values':values}]}}

class PrometheusTests(unittest.TestCase):
    def test_disabled(self):
        self.assertEqual(PrometheusCollector().collect('demo').evidence, [])

    def test_valid_multiple_containers_and_rate(self):
        transport = Mock()
        transport.request.return_value = prometheus([sample(), sample('sidecar')])
        result = PrometheusCollector('http://metrics', transport=transport).collect('demo')
        self.assertEqual(len(result.evidence), len(QUERIES)*2)
        self.assertEqual({e.container for e in result.evidence}, {'app','sidecar'})
        self.assertIn('rate(', transport.request.call_args_list[0].kwargs['params']['query'])
        self.assertTrue(all(e.source == 'prometheus' and e.timestamp for e in result.evidence))

    def test_empty(self):
        transport = Mock(); transport.request.return_value = prometheus()
        result = PrometheusCollector('http://metrics', transport=transport).collect('demo')
        self.assertEqual(result.evidence, []); self.assertFalse(result.warnings)

    def test_timeout(self):
        transport = Mock(); transport.request.side_effect = TimeoutError('private-token')
        result = PrometheusCollector('http://metrics', transport=transport).collect('demo')
        self.assertEqual(len(result.warnings), len(QUERIES))
        self.assertNotIn('private-token', str(result))

    def test_malformed(self):
        transport = Mock(); transport.request.return_value = {'status':'success','data':None}
        self.assertTrue(PrometheusCollector('http://metrics', transport=transport).collect('demo').warnings)

    def test_partial_failure(self):
        transport = Mock(); transport.request.side_effect = [TimeoutError()] + [prometheus([sample()])]*(len(QUERIES)-1)
        result = PrometheusCollector('http://metrics', transport=transport).collect('demo')
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(len(result.evidence), len(QUERIES)-1)

    def test_invalid_samples_and_namespace(self):
        transport = Mock(); transport.request.return_value = prometheus([sample(value='NaN'), sample(namespace='other'), {'metric':{}}])
        result = PrometheusCollector('http://metrics', transport=transport).collect('demo')
        self.assertFalse(result.evidence); self.assertTrue(result.warnings)
        with self.assertRaises(ValueError):
            PrometheusCollector('http://metrics').collect('demo"}')

    def test_upstream_warning(self):
        transport = Mock(); response=prometheus(); response['warnings']=['private upstream details']
        transport.request.return_value=response
        result=PrometheusCollector('http://metrics',transport=transport).collect('demo')
        self.assertTrue(result.warnings); self.assertNotIn('private upstream',str(result))

class LokiTests(unittest.TestCase):
    def test_disabled(self):
        self.assertFalse(LokiCollector().collect('demo').evidence)

    def test_normal_and_error(self):
        transport=Mock(); transport.request.return_value=loki(['startup ok', 'ERROR connection refused'])
        result=LokiCollector('http://logs',transport=transport).collect('demo','demo-app','app')
        self.assertEqual(len(result.evidence),1)
        self.assertIn('refused',result.evidence[0].message)
        self.assertEqual(transport.request.call_args.kwargs['params']['query'],'{namespace="demo",pod="demo-app",container="app"}')

    def test_timeout(self):
        transport=Mock(); transport.request.side_effect=TimeoutError('private')
        result=LokiCollector('http://logs',transport=transport).collect('demo')
        self.assertTrue(result.warnings); self.assertNotIn('private',str(result))

    def test_empty_and_malformed(self):
        transport=Mock(); transport.request.return_value=loki()
        self.assertFalse(LokiCollector('http://logs',transport=transport).collect('demo').evidence)
        transport.request.return_value={}
        self.assertTrue(LokiCollector('http://logs',transport=transport).collect('demo').warnings)

    def test_credentials_and_truncation(self):
        transport=Mock(); transport.request.return_value=loki(['ERROR Authorization: Bearer private_token password="test-password" '+('x'*2000)])
        message=LokiCollector('http://logs',transport=transport).collect('demo').evidence[0].message
        self.assertNotIn('private_token',message); self.assertNotIn('test-password',message)
        self.assertLessEqual(len(message),1000)

    def test_time_bounds_limit_and_invalid_selector(self):
        transport=Mock(); transport.request.return_value=loki(['ERROR failed']*5)
        collector=LokiCollector('http://logs',line_limit=2,transport=transport)
        result=collector.collect('demo',incident_time=datetime.now(timezone.utc)-timedelta(minutes=30))
        self.assertEqual(len(result.evidence),2)
        params=transport.request.call_args.kwargs['params']
        self.assertLess(int(params['start']),int(params['end']))
        with self.assertRaises(ValueError): collector.collect('demo"}')
        with self.assertRaises(ValueError): LokiCollector(minutes=0)
        with self.assertRaises(ValueError): LokiCollector(namespace_label='bad-label')

    def test_label_mapping_and_scope(self):
        transport=Mock(); transport.request.return_value=loki(['ERROR failed'],{'ns':'demo','pod_name':'demo-app','container_name':'app'})
        collector=LokiCollector('http://logs',transport=transport,namespace_label='ns',pod_label='pod_name',container_label='container_name')
        self.assertEqual(len(collector.collect('demo').evidence),1)
        self.assertFalse(collector.collect('other').evidence)

class CorrelationTests(unittest.TestCase):
    def test_all_seven_fixtures(self):
        for path in FIXTURES.glob('*.json'):
            with self.subTest(path=path.name):
                snapshot, expected=load_fixture(path)
                reports=CorrelationEngine().analyze(snapshot)
                self.assertIn(expected,[i.category for i in reports])
                for i in reports:
                    self.assertFalse(i.automatic_action_taken)
                    self.assertIn(i.confidence,('high','medium','low'))
                    self.assertTrue(i.confidence_reason)

    def test_healthy(self):
        snapshot=Snapshot('demo',[PodEvidence('pod','demo','uid','Running',[ContainerEvidence('app','regular','running',0,ready=True)])])
        self.assertFalse(CorrelationEngine().analyze(snapshot))

    def test_db_requires_refused_and_endpoint(self):
        snapshot=fixture(); snapshot.evidence[0].message='connection refused'
        self.assertEqual(CorrelationEngine().analyze(snapshot)[0].category,'CrashLoopBackOff')

    def test_ingress_requires_readiness(self):
        snapshot=fixture('06_ingress_routing'); snapshot.pods[0].containers[0].ready=False
        self.assertFalse(CorrelationEngine().analyze(snapshot))

    def test_successful_pull_event_is_not_failure_evidence(self):
        snapshot=fixture('02_imagepull')
        snapshot.pods[0].events[0].reason='Pulled'
        snapshot.pods[0].events[0].message='Successfully pulled image demo'
        self.assertEqual(CorrelationEngine().analyze(snapshot)[0].category,'ImagePullBackOff')

    def test_memory_requires_limit(self):
        snapshot=fixture('03_oom'); snapshot.evidence=snapshot.evidence[:1]
        self.assertEqual(CorrelationEngine().analyze(snapshot)[0].category,'OOMKilled')

    def test_high_cpu_requires_restart_evidence(self):
        snapshot=fixture('04_high_cpu'); snapshot.evidence=snapshot.evidence[:1]
        self.assertFalse(CorrelationEngine().analyze(snapshot))

    def test_historical_restart(self):
        snapshot=fixture('06_ingress_routing'); snapshot.evidence=[]
        snapshot.pods[0].containers[0].restart_count=6
        reports=CorrelationEngine().analyze(snapshot)
        self.assertEqual(reports[0].category,'HISTORICAL_RESTART_WARNING')

    def test_stale_evidence_not_correlated(self):
        snapshot=fixture(); snapshot.evidence[0].timestamp=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        self.assertEqual(CorrelationEngine().analyze(snapshot)[0].category,'CrashLoopBackOff')

    def test_cross_pod_container_namespace_not_correlated(self):
        for attr in ('pod','container','namespace'):
            snapshot=fixture(); setattr(snapshot.evidence[0],attr,'different')
            self.assertEqual(CorrelationEngine().analyze(snapshot)[0].category,'CrashLoopBackOff')

    def test_structured_fields_and_dedup(self):
        first, second=incident(),incident()
        self.assertNotEqual(first.incident_id,second.incident_id)
        self.assertEqual(first.deduplication_key,second.deduplication_key)
        self.assertIn('timestamp',first.to_dict()); self.assertIn('source',first.to_dict()['evidence'][0])

class LLMTests(unittest.TestCase):
    def test_disabled(self):
        self.assertIsNone(LLMAnalyzer().analyze(incident()))

    def test_mock_success(self):
        provider=Mock(); provider.analyze.return_value={'summary':'Insufficient evidence','probable_causes':[], 'recommended_actions':[], 'additional_checks':['Review events']}
        self.assertEqual(LLMAnalyzer(provider).analyze(incident())['summary'],'Insufficient evidence')

    def test_malformed(self):
        provider=Mock(); provider.analyze.return_value={'summary':123}
        self.assertEqual(LLMAnalyzer(provider).analyze(incident())['status'],'unavailable')

    def test_timeout(self):
        provider=Mock(); provider.analyze.side_effect=TimeoutError('private')
        self.assertNotIn('private',str(LLMAnalyzer(provider).analyze(incident())))

    def test_openai_disabled_without_key(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertIsNone(OpenAIProvider(model='configured-model').analyze(incident()))

    def test_openai_structured_no_tools(self):
        transport=Mock(); output={'summary':'hypothesis','probable_causes':[], 'recommended_actions':[], 'additional_checks':[]}
        transport.request.return_value={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(output)}]}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake-unit-test-value'}):
            self.assertEqual(LLMAnalyzer(OpenAIProvider(model='configured-model',transport=transport)).analyze(incident()),output)
        payload=transport.request.call_args.kwargs['payload']
        self.assertNotIn('tools',payload); self.assertFalse(payload['store'])
        self.assertTrue(payload['text']['format']['strict'])

    def test_refusal_and_incomplete(self):
        transport=Mock(); transport.request.return_value={'status':'incomplete'}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake-unit-test-value'}):
            self.assertEqual(LLMAnalyzer(OpenAIProvider(model='configured-model',transport=transport)).analyze(incident())['status'],'unavailable')

    def test_output_sanitized_and_limits(self):
        provider=Mock(); provider.analyze.return_value={'summary':'password=fake-sensitive-value','probable_causes':[], 'recommended_actions':[], 'additional_checks':[]}
        self.assertNotIn('fake-sensitive-value',LLMAnalyzer(provider).analyze(incident())['summary'])
        provider.analyze.return_value['additional_checks']=['x']*11
        self.assertEqual(LLMAnalyzer(provider).analyze(incident())['status'],'unavailable')

class DiscordTests(unittest.TestCase):
    def setUp(self):
        self.environment=patch.dict(os.environ,{},clear=True); self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_disabled(self):
        self.assertEqual(DiscordNotifier().notify(incident()),'disabled')

    def test_success_and_duplicate(self):
        os.environ['DISCORD_WEBHOOK_URL']='https://discord.com/api/webhooks/123/fake-unit-test-value'
        transport=Mock(); notifier=DiscordNotifier(transport=transport)
        self.assertEqual(notifier.notify(incident()),'sent')
        self.assertEqual(notifier.notify(incident()),'duplicate')
        self.assertEqual(transport.request.call_count,1)
        payload=transport.request.call_args.kwargs['payload']
        self.assertLessEqual(len(payload['content']),1900)
        self.assertEqual(payload['allowed_mentions'],{'parse':[]})

    def test_failure_does_not_mark_sent(self):
        os.environ['DISCORD_WEBHOOK_URL']='https://discord.com/api/webhooks/123/fake-unit-test-value'
        transport=Mock(); transport.request.side_effect=TimeoutError()
        notifier=DiscordNotifier(transport=transport)
        self.assertEqual(notifier.notify(incident()),'unavailable')
        transport.request.side_effect=None
        self.assertEqual(notifier.notify(incident()),'sent')

    def test_invalid_endpoint(self):
        os.environ['DISCORD_WEBHOOK_URL']='http://internal'
        self.assertEqual(DiscordNotifier().notify(incident()),'invalid_configuration')

class APITests(unittest.TestCase):
    def setUp(self):
        self.engine=Mock(); self.report=incident(); self.engine.analyze.return_value=([self.report],[])
        self.client=TestClient(create_app(Settings(allowed_namespaces=('demo',)),engine=self.engine))

    def test_health(self):
        self.assertEqual(self.client.get('/health').json()['mode'],'read-only')
        self.engine.analyze.assert_not_called()

    def test_analyze_and_retrieve(self):
        response=self.client.post('/api/analyze',json={'namespace':'demo'})
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['automatic_action_taken'])
        self.assertEqual(len(self.client.get('/api/incidents').json()['incidents']),1)
        self.assertEqual(self.client.get('/api/incidents/'+self.report.incident_id).status_code,200)

    def test_concurrent_analysis_rejected(self):
        import threading
        started, release=threading.Event(), threading.Event()
        def blocking(namespace):
            started.set()
            release.wait(5)
            return [],[]
        self.engine.analyze.side_effect=blocking
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.client.post('/api/analyze',json={'namespace':'demo'})))
        worker.start()
        try:
            self.assertTrue(started.wait(5))
            self.assertEqual(self.client.post('/api/analyze',json={'namespace':'demo'}).status_code,429)
        finally:
            release.set(); worker.join(5)
        self.assertEqual(results[0].status_code,200)

    def test_validation_allowlist_and_commands(self):
        self.assertEqual(self.client.post('/api/analyze',json={'namespace':'production'}).status_code,403)
        self.assertEqual(self.client.post('/api/analyze',json={'namespace':'demo; rm'}).status_code,422)
        self.assertEqual(self.client.post('/api/analyze',json={'namespace':'demo','command':'kubectl'}).status_code,422)
        self.engine.analyze.assert_not_called()

    def test_unknown_and_invalid_ids(self):
        self.assertEqual(self.client.get('/api/incidents/00000000-0000-0000-0000-000000000000').status_code,404)
        self.assertEqual(self.client.get('/api/incidents/../secret').status_code,404)
        self.assertEqual(self.client.get('/api/incidents/not-uuid').status_code,422)

    def test_collection_failure(self):
        self.engine.analyze.side_effect=CollectionError('private')
        response=self.client.post('/api/analyze',json={'namespace':'demo'})
        self.assertEqual(response.status_code,503); self.assertNotIn('private',response.text)

    def test_authentication(self):
        client=TestClient(create_app(Settings(allowed_namespaces=('demo',),api_token='fake-api-value'),engine=self.engine))
        self.assertEqual(client.get('/api/incidents').status_code,401)
        self.assertEqual(client.get('/api/incidents',headers={'Authorization':'Bearer fake-api-value'}).status_code,200)

    def test_webhook_disabled_and_auth(self):
        payload={'alerts':[{'status':'firing','labels':{'namespace':'demo'}}]}
        self.assertEqual(self.client.post('/api/webhooks/alertmanager',json=payload).status_code,503)
        client=TestClient(create_app(Settings(allowed_namespaces=('demo',),webhook_token='fake-hook-value'),engine=self.engine))
        self.assertEqual(client.post('/api/webhooks/alertmanager',json=payload).status_code,401)
        self.assertEqual(client.post('/api/webhooks/alertmanager',json=payload,headers={'X-Alertmanager-Token':'fake-hook-value'}).status_code,200)

    def test_webhook_scope_and_resolved(self):
        client=TestClient(create_app(Settings(allowed_namespaces=('demo',),webhook_token='fake-hook-value'),engine=self.engine))
        headers={'X-Alertmanager-Token':'fake-hook-value'}
        self.assertEqual(client.post('/api/webhooks/alertmanager',json={'alerts':[{'status':'firing','labels':{'namespace':'other'}}]},headers=headers).status_code,403)
        self.assertEqual(client.post('/api/webhooks/alertmanager',json={'alerts':[{'status':'resolved','labels':{'namespace':'demo'}}]},headers=headers).json()['analyses'],[])

    def test_invalid_list_limit(self):
        self.assertEqual(self.client.get('/api/incidents?limit=0').status_code,422)

class PipelineSecurityTests(unittest.TestCase):
    def test_optional_failures_keep_findings_and_close(self):
        collector=Mock(); collector.collect.return_value=fixture()
        metrics=Mock(); metrics.collect.side_effect=TimeoutError()
        logs=Mock(); logs.collect.return_value=CollectionResult()
        engine=AnalysisEngine(Settings(allowed_namespaces=('demo',)),collector_factory=lambda:collector,prometheus=metrics,loki=logs)
        reports,warnings=engine.analyze('demo')
        self.assertTrue(reports); self.assertTrue(warnings); collector.close.assert_called_once()
        with self.assertRaises(ValueError): engine.analyze('other')

    def test_llm_and_notification_failures_keep_findings(self):
        metrics=Mock(); metrics.collect.return_value=CollectionResult()
        logs=Mock(); logs.collect.return_value=CollectionResult()
        llm=Mock(); llm.analyze.side_effect=TimeoutError()
        notifier=Mock(); notifier.notify.side_effect=TimeoutError()
        engine=AnalysisEngine(Settings(allowed_namespaces=('demo',),notifications_enabled=True),
                              prometheus=metrics,loki=logs,llm=llm,notifier=notifier)
        reports,warnings=engine.analyze_snapshot(fixture())
        self.assertTrue(reports)
        self.assertEqual(reports[0].llm_analysis['status'],'unavailable')
        self.assertIn('discord: notification unavailable',warnings)

    def test_store_eviction(self):
        store=IncidentStore(capacity=1); first,second=incident(),incident()
        store.add_all([first,second]); self.assertIsNone(store.get(first.incident_id))
        result=store.get(second.incident_id); result['summary']='changed'
        self.assertNotEqual(store.get(second.incident_id)['summary'],'changed')

    def test_bounded_schedule(self):
        engine=Mock(); engine.analyze.return_value=([],[])
        self.assertEqual(list(scheduled_analysis(engine,'demo')), [([],[])])
        with self.assertRaises(ValueError): list(scheduled_analysis(engine,'demo',iterations=0))

    def test_masking_patterns(self):
        values=['Authorization: Basic fake-value','Bearer fake-value','api_key=fake-value','password: "fake-value"',
                'secret=fake-value','Cookie: session=fake-value','https://user:fake-value@db','token=fake-value']
        for value in values:
            with self.subTest(value=value): self.assertNotIn('fake-value',sanitize(value))

    def test_http_rejects_credentials_and_bad_scheme(self):
        for url in ('file:///tmp/test','https://user:pass@example.com'):
            with self.assertRaises(ValueError): HTTPTransport().request('GET',url)

    def test_pagination_repeated_token_is_bounded(self):
        from types import SimpleNamespace
        api=Mock(); api.list_namespaced_pod.return_value=SimpleNamespace(items=[],metadata=SimpleNamespace(_continue='again'))
        with self.assertRaises(CollectionError): KubernetesCollector(api).collect('demo')
        self.assertEqual(api.list_namespaced_pod.call_count,2)

if __name__=='__main__':
    unittest.main()
