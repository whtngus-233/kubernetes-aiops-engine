"""Deterministic hypotheses, never automatic remediation."""
from app.models import Incident, Snapshot

RULES = {
    "CrashLoopBackOff": ("critical", "애플리케이션 반복 종료 또는 시작 설정 오류 가능성",
        ["이전 컨테이너 로그와 종료 코드를 확인하세요.", "환경 설정, 의존 서비스, startup/liveness probe를 검토하세요."]),
    "ImagePullBackOff": ("critical", "이미지 경로/태그, 레지스트리 인증 또는 네트워크 문제 가능성",
        ["Event에서 이미지 pull 실패 메시지를 확인하세요.", "이미지 존재 여부, 레지스트리 접근 권한과 연결을 검토하세요."]),
    "ErrImagePull": ("critical", "이미지 다운로드 실패",
        ["이미지 이름/태그와 레지스트리 인증 및 연결을 확인하세요."]),
    "Error": ("critical", "컨테이너 비정상 종료",
        ["종료 코드와 애플리케이션 로그, 설정 및 의존 서비스를 확인하세요."]),
    "OOMKilled": ("critical", "컨테이너 메모리 한도 초과 가능성",
        ["메모리 사용량 추이, 한도와 메모리 누수를 검토하세요."]),
    "Pending": ("warning", "스케줄링, 볼륨 준비 또는 컨테이너 시작 대기",
        ["FailedScheduling/FailedMount Event를 확인하세요.", "노드 용량, requests, affinity/taint 및 PVC 상태를 검토하세요."]),
    "HighRestartCount": ("warning", "누적 재시작 횟수가 임계값 이상: 과거 장애 또는 반복 종료 가능성",
        ["재시작 시점과 이전 종료 사유를 확인하세요.", "누적값만으로 현재 장애를 확정하지 말고 재시작 증가율을 검토하세요."]),
    "Failed": ("critical", "Pod 실패 상태",
        ["컨테이너 종료 사유와 Pod Event를 확인하세요."]),
}


class RuleEngine:
    def __init__(self, restart_threshold=5):
        if isinstance(restart_threshold, bool) or not isinstance(restart_threshold, int) or restart_threshold < 1:
            raise ValueError("restart_threshold는 1 이상의 정수여야 합니다.")
        self.restart_threshold = restart_threshold

    def analyze(self, snapshot: Snapshot):
        incidents = []
        def add(pod, category, container, evidence):
            severity, cause, recommendations = RULES[category]
            incidents.append(Incident(pod, category, severity, container, evidence,
                                      cause, list(recommendations)))
        for pod in snapshot.pods:
            if pod.phase in ("Pending", "Failed"):
                add(pod, pod.phase, None, f"phase={pod.phase}")
            for c in pod.containers:
                reason = c.waiting_reason or c.terminated_reason
                if reason in RULES and reason not in ("Pending", "Failed", "HighRestartCount"):
                    add(pod, reason, c.name, f"{c.kind}: state={c.state}, reason={reason}, exit={c.exit_code}")
                elif c.state == "terminated" and c.exit_code not in (None, 0):
                    add(pod, "Error", c.name, f"종료 사유={c.terminated_reason}, exit={c.exit_code}")
                if c.restart_count >= self.restart_threshold:
                    add(pod, "HighRestartCount", c.name,
                        f"restarts={c.restart_count}, previous={c.previous_terminated_reason or 'unknown'}")
        return incidents
