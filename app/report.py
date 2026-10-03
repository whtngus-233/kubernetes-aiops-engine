from datetime import datetime, timezone
from app.security import sanitize


def safe(value):
    # Prevent API-controlled text from injecting terminal control sequences.
    return "".join(c if c.isprintable() else " " for c in sanitize(value))


def render_report(snapshot, incidents):
    lines = ["Kubernetes AIOps Incident Report", f"조회 시각: {datetime.now(timezone.utc).isoformat()}",
             f"Namespace: {safe(snapshot.namespace)} | Pods: {len(snapshot.pods)} | Findings: {len(incidents)}",
             "모드: READ-ONLY / 원인은 규칙 기반 가설이며 자동 조치는 실행하지 않습니다."]
    for warning in snapshot.warnings:
        lines.append(f"WARNING: {safe(warning)}")
    for pod in snapshot.pods:
        lines.append(f"\nPod: {safe(pod.namespace)}/{safe(pod.name)} | phase={safe(pod.phase)}")
        for c in pod.containers:
            lines.append(f"  Container: {safe(c.name)} ({c.kind}) state={c.state} restarts={c.restart_count} "
                         f"waiting={safe(c.waiting_reason or '-')} terminated={safe(c.terminated_reason or '-')} "
                         f"previous={safe(c.previous_terminated_reason or '-')} exit={c.exit_code}")
        findings = [i for i in incidents if i.pod is pod]
        for i in findings:
            lines.extend([f"  [{i.severity.upper()}] {i.category} container={safe(i.container or '-')}",
                          f"    증거: {safe(i.evidence)}", f"    추정 원인: {safe(i.probable_cause)}"])
            lines.extend(f"    제안: {safe(r)}" for r in i.recommendations)
        if findings:
            lines.append("  관련 Events:" if pod.events else "  관련 Events: 없음 (보존 기간 만료 가능)")
            for e in pod.events[-20:]:
                lines.append(f"    {safe(e.timestamp)} {safe(e.type)} {safe(e.reason)} x{e.count}: {safe(e.message)}")
            if len(pod.events) > 20:
                lines.append(f"    이전 Event {len(pod.events) - 20}개 표시 생략")
    if not incidents:
        lines.append("\n설정된 규칙에서 이상 징후가 발견되지 않았습니다. 전체 서비스 정상 여부를 보장하지 않습니다.")
    return "\n".join(lines)


def render_structured(incidents, warnings=()):
    lines = ['Kubernetes AIOps Incident Report | READ-ONLY']
    lines.extend('WARNING: ' + safe(w) for w in warnings)
    for incident in incidents:
        data = incident.to_dict()
        lines.append(f"[{data['severity']}] {data['namespace']}/{data['pod']} {data['category']} ({data['confidence']})")
        lines.append('  ' + safe(data['summary']))
        lines.append('  Confidence: ' + safe(data['confidence_reason']))
        for e in data['evidence'][:10]:
            lines.append(f"  {safe(e['source'])} {safe(e['timestamp'])} {safe(e['key'])}={safe(e['value'])} {safe(e['message'])}")
        lines.extend('  Review: ' + safe(a) for a in data['recommended_actions'])
        if data['llm_analysis']:
            lines.append('  LLM advisory: ' + safe(data['llm_analysis']))
    if not incidents:
        lines.append('No configured rule findings. This does not guarantee service health.')
    return '\n'.join(lines)
