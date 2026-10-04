# Reusable Kubernetes AIOps Incident Analysis Platform

## 문제와 아이디어

MODUI EKS 운영 중 장애 분석을 위해 Pod, Service, Ingress와 로그를 반복 확인해야 했다.
“반복되는 장애 분석 과정을 자동화할 수 없을까?”에서 시작해 특정 MODUI 서비스에 종속되지 않는
Reusable Kubernetes AIOps Incident Analysis Engine을 설계했다.

## 해결과 기여

기존 Kubernetes Python MVP를 audit하고 호환 테스트를 유지하면서 evidence pipeline을 확장했다.
Pod/Container/Event 상태, Prometheus CPU rate·메모리·restart, Loki sanitized signal을 공통 모델로 연결하고
Rule Engine과 시간/identity correlation으로 원인 후보를 설명한다. LLM-assisted RCA는 도구 권한 없이
보조 JSON만 제공하며 human-in-the-loop으로 운영 결정을 남긴다.
Discord 알림/dedup, FastAPI namespace allowlist/incident store, Docker/Helm 최소 RBAC로 재사용을 위한 interface와 패키징 예제를 제공했다.

## 검증과 정직한 범위

이전 확장 작업의 검증 기록에서 실제 modui-prod를 READ-ONLY로 조회한 Python Collector가 성공했다.
Pod 조회에서도 11개가 Running으로 확인됐다. 관측 API 일부 조회는 timeout되어
Prometheus/Loki live integration은 확인하지 못했다. Grafana proxy 이름만으로 backend 존재를 주장하지 않는다.
운영 서비스에는 장애를 주입하지 않았으며 offline mock fault scenarios 7개와 회귀 테스트로 검증했다.
LLM/Discord는 mock 검증이다. 이번 Docker build는 socket 권한 거부로 완료하지 못했고 Helm 설치와 AWS/DB/애플리케이션 변경은 수행하지 않았다.
상세 재현 명령과 결과는 validation.md를 참고한다.

## 포트폴리오에서 보여줄 것

1. offline demo로 DB connection refused/image pull/OOM/scheduling의 증거와 분류를 설명한다.
2. 단일 상태만으로 원인을 확정하지 않고 low confidence와 additional checks를 제공하는 사례를 보인다.
3. source/time/window와 Pod/container 경계를 설명한다.
4. 선택 collector/LLM 장애가 전체 분석을 중단하지 않는 테스트를 보여준다.
5. 최소 RBAC, secret masking, no-tools LLM과 실제 운영 READ-ONLY 검증을 강조한다.

운영 자동복구 시스템이나 학습된 이상 탐지 모델로 소개하지 않는다. MTTR 감소/비용 절감/LLM 정확도는
현재 측정하지 않았으므로 수치로 주장하지 않는다. 후속 평가에서는 ground truth incident와 precision/recall,
조사 시간, false-positive, 데이터 전송량과 비용을 측정할 수 있다.
