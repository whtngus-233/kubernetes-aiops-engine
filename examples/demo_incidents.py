"""Offline fixtures only: no Kubernetes, AWS, HTTP or notification requests."""
import argparse
import json
from pathlib import Path
from app.models import Snapshot, PodEvidence, ContainerEvidence, EventEvidence, IncidentEvidence, utc_now
from app.analyzers.correlation import CorrelationEngine
from app.report import render_structured

FIXTURES = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures'

def load_fixture(path):
    data = json.loads(path.read_text())
    now = utc_now()
    pods = []
    for p in data['pods']:
        pods.append(PodEvidence(p['name'], data['namespace'], p['name'] + '-uid', p['phase'],
            [ContainerEvidence(**c) for c in p.get('containers', [])],
            [EventEvidence(timestamp=now, **e) for e in p.get('events', [])]))
    snapshot = Snapshot(data['namespace'], pods)
    snapshot.evidence = [IncidentEvidence(timestamp=now, namespace=data['namespace'], **e) for e in data.get('evidence', [])]
    return snapshot, data['expected_category']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--format', choices=('terminal', 'json'), default='terminal')
    args = parser.parse_args()
    results = []
    paths = sorted(FIXTURES.glob('*.json'))
    if len(paths) != 7:
        raise RuntimeError('Expected seven offline fixtures')
    for path in paths:
        snapshot, expected = load_fixture(path)
        reports = CorrelationEngine().analyze(snapshot, 'offline-demo')
        if expected not in [i.category for i in reports]:
            raise RuntimeError('Fixture expectation failed: ' + path.name)
        results.extend(reports)
        if args.format == 'terminal':
            print(path.stem + ': ' + render_structured(reports))
    if args.format == 'json':
        print(json.dumps([i.to_dict() for i in results], ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
