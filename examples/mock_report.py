"""Offline example: no kubeconfig, credentials or cluster access."""
from app.models import ContainerEvidence, PodEvidence, Snapshot
from app.analyzers.rules import RuleEngine
from app.report import render_report

snapshot = Snapshot('example', [
    PodEvidence('healthy', 'example', 'mock-1', 'Running',
                [ContainerEvidence('web', 'regular', 'running', 0)]),
    PodEvidence('crashing', 'example', 'mock-2', 'Running',
                [ContainerEvidence('web', 'regular', 'waiting', 8,
                                   waiting_reason='CrashLoopBackOff', previous_terminated_reason='Error')]),
])
if __name__ == '__main__':
    print(render_report(snapshot, RuleEngine().analyze(snapshot)))
