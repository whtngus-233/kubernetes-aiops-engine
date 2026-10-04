# Project audit — 2026-10-03

이 문서는 초기 확장 작업의 이력입니다. 현재 최종 정리 작업의 상태와 검증은 [validation.md](validation.md)를 참고하세요.
작업 시작 시 전체 프로젝트 소스는 Git untracked 상태였습니다. 기존 코드는 삭제하지 않고 확장했습니다.
기본 14개 unittest가 통과했고 Python 3.12 virtualenv에 Kubernetes 36.0.3/PyYAML 6.0.3이 있었습니다.

장점: dataclass evidence, Event Pod UID 연결, regular/init/ephemeral 수집, pagination/timeout,
Pod 실패와 Event 부분 실패 구분, sanitized 오류, current/previous termination 구분,
기존 CLI/YAML 검증과 client close, 변경 API를 사용하지 않는 작은 수집 경계.

문제: 외부 collector/analyzer/notifier는 NotImplementedError인 placeholder,
기본 namespace가 특정 서비스에 묶임, 증거 source/수집 timestamp 부족,
readiness/limit 및 correlation 없음, structured report/API/store/실행 가능한 offline faults 없음,
Docker 단일 snapshot만 제공, Helm/ADR/면접 설명 부재.

개선: 기존 RuleEngine contract 유지, 기본 namespace=default, normalized evidence와 별도 correlation,
source/time/window, optional bounded backend adapters, read-only advisory API 및 배포 예제.
Credential 파일/내용과 Pod env는 조사하지 않았습니다. 현재 context 이름만 확인했습니다.
Git commit/push/remote 변경, cluster/AWS/DB/MODUI 코드 변경은 수행하지 않았습니다.


## Engineering baseline 감사

clean HEAD 4ae4853에서 README/docs/app/tests/examples/scripts/charts와 Git 이력을 대조했다.
기존 구현의 collector/rules/correlation/LLM/report/API/store/security/Docker/Helm을 유지했다.
발견 및 수정: CLI가 allowlist를 덮어썼음, engine/scheduler 간 overlap guard 없음,
snapshot을 반복 분석하면 optional evidence 누적, scheduler NaN/float bounds 검증 부족과
예외 시 iteration 중단, API POST bytes 미제한, 요청만 timeout이고 pagination/advisory 누적 budget 부재.
TestClient 최소 재현은 socketpair send EPERM과 asyncio wakeup 대기였고 pytest console import도 실패했다.
수정 및 현재 검증 결과는 validation.md가 기준이며 위 초기 감사의 과거 결과와 구분한다.

## Final health investigation — 2026-10-03

Preserved all existing changes. Converted health to async; replaced shell-form Docker probe
with direct stdlib Python probe without increasing 3s timeout. Added worker-capacity/probe
failure tests and offline HOST-script safety tests. No Docker command or Kubernetes write
was executed. HOST final runtime verification and CPU/PIDS/zombie cause confirmation remain
pending; commit/push/tag are explicitly deferred. See [host-validation.md](host-validation.md).
