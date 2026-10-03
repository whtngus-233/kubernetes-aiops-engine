# Final project report

## 1. 최종 프로젝트 구조

```text
app/
  collectors/{kubernetes,prometheus,loki}.py
  analyzers/{rules,correlation,llm}.py
  notifiers/discord.py
  models.py evidence.py structured.py report.py
  config.py security.py http.py engine.py api.py store.py scheduling.py main.py
tests/
  test_engine.py test_platform.py fixtures/01..07_*.json
examples/
  mock_report.py demo_incidents.py
charts/aiops-engine/
  Chart.yaml values.yaml values.schema.json templates/ README.md
docs/
  audit.md architecture.md integration.md security.md validation.md
  portfolio.md interview.md final-report.md adr/001..004-*.md
scripts/security_scan.py
Dockerfile .dockerignore .gitignore .env.example config.example.yaml
requirements.txt requirements-dev.txt README.md
```

## 2. 구현 완료 기능

Kubernetes MVP/14개 회귀 테스트 유지, normalized evidence, Prometheus rate/status와 partial failures,
Loki signal/time/limit/sanitization, 7개 correlation scenarios와 historical warning,
terminal/JSON/explicit file output, LLM provider abstraction/strict output/no tools/fallback,
Discord env-only webhook/dedup, FastAPI allowlist/auth/memory store/concurrency guard,
bounded scheduling/Alertmanager interface, Docker/Helm examples, ADR/portfolio/interview 문서.

## 3. 미검증 연동과 후속 기능

실제 Prometheus/Loki 안전 endpoint를 확인하지 못해 live query는 미검증이다.
실제 LLM/Discord 호출은 수행하지 않고 mock으로 검증했다.
memory growth/peak time-series, Service/Ingress topology evidence, metric/log Pod UID,
backend bearer/tenant/API proxy transport와 persistent/distributed store는 후속 개선이다.
자동 복구는 안전 설계에 따라 의도적으로 제공하지 않는다.

## 4. Kubernetes 실제 검증 (이전 기록)

확장 Python Collector READ-ONLY CLI exit 0, rule findings 없음.
별도 Pod 조회에서 modui-prod 11개 Running 확인. 전체 서비스 건강을 의미하지 않는다.

## 5. Prometheus 실제 검증

Service/namespace/cluster-wide discovery timeout 때문에 backend 설치/endpoint 미확인.
Prometheus/kube-state-metrics/node-exporter가 없다고 단정하지 않았다. mock tests와 문서 제공.

## 6. Loki 실제 검증

안전 query endpoint 미확인으로 live query 미실행. time/selector/limit/masking/failure mock 검증.
Grafana proxy Pod/EndpointSlice의 이름만으로 Loki backend 존재를 판단하지 않았다.

## 7. LLM 검증

disabled/success/malformed/timeout/incomplete/schema/no tools/sanitization mock 검증.
실제 API key 출력이나 외부 호출 없음. 규칙 결과 유지.

## 8. Discord 검증

disabled/mock success/duplicate/failure retry/endpoint rejection 검증. 실제 발송 없음.

## 9. FastAPI 검증

health/analyze/list/UUID retrieval, allowlist/extra fields/authentication,
collector error/concurrency 429와 webhook scope/auth 검증. local mock TestClient로만 실행.

## 10. 테스트

이전 확장 기록에서는 기존 14개 포함 unittest 69개와 pytest 69개 / subtests 31개가 통과했다.
이번 전체 unittest/pytest는 180초 timeout으로 완료되지 않았다. API 제외 pytest는 59개와 subtests 31개가 통과했다.
대기와 진단 실패의 상세 한계는 [validation.md](validation.md)에 기록한다.
이번 Python compile, pip check, 7개 fixture의 terminal/JSON Demo는 성공했다.

## 11. Security

Secret pattern/source scan, unsafe command/mutation/YAML 패턴 및 whitespace/Git diff 검사 통과.
non-root/read-only runtime, namespace별 최소 RBAC, env-only secrets, sanitized evidence 적용.
heuristic masking과 dependency compatibility check는 PII/vulnerability 전수 검사를 대체하지 않는다.

## 12. Docker/Helm 준비 상태

Dockerfile/non-root/healthcheck/context allowlist 작성. Docker build 미실행.
이번 chart lint와 `helm template demo charts/aiops-engine --namespace aiops`는 성공했다.
multiple namespace render/static RBAC 검사는 이전 기록이다. 실제 설치 없음.

## 13. 실제 배포 전 작업

backend endpoints/labels/auth/tenant, API token/TLS/network, 기존 Secret 관리와 운영 values 검토,
이미지 build/vulnerability scan 및 실제 외부 연동 검증 필요. 한 worker/replica로 시작.

## 14. 포트폴리오 강조

기존 코드 보존과 회귀 검증, reusable evidence pipeline, rule-before-LLM,
외부 장애 isolation, 운영 EKS READ-ONLY 검증과 offline fault demo를 강조한다.

## 15. 면접 핵심

Running과 서비스 정상의 차이, 누적 restart와 현재 장애 구분,
metrics/logs의 역할, correlation 근거와 confidence 한계,
LLM hallucination 대응과 human-in-the-loop/RBAC 경계를 설명한다.

## 16. 다음 개선 우선순위

1. 안전한 Prometheus/Loki 실제 연결과 환경별 query/label/auth 검증.
2. 메모리/restart time-series와 Service/Ingress/Pod UID evidence 강화.
3. shared store, persistent dedup와 worker queue/rate/body limits.
4. ground-truth 기반 rule/LLM accuracy·false positives·조사 시간 평가.
5. CI/SBOM/image security와 dev TestClient dependency migration.

실제 EKS/AWS/DB/MODUI 서비스 변경, 운영 장애 주입·부하 테스트, 자동복구,
Docker build/Helm 설치와 운영 배포는 수행하지 않았다. 최종 문서 정리의 Git 상태는 최종 보고로 확인한다.
