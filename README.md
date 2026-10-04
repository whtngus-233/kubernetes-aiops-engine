# Kubernetes AIOps Incident Analysis Platform

Python 3.12 기반 **Kubernetes 장애 증거 수집 및 원인 추론 보조 플랫폼**입니다.
Pod 상태, Event, Metrics, Logs를 시간과 workload identity로 연결해 운영자가 검토할
구조화 보고서와 추가 확인 방법을 제공합니다. **클러스터 변경과 자동 복구는 실행하지 않습니다.**

## 문제와 목적

Kubernetes 장애 조사에서 반복되는 Pod → Event → Metrics → Logs 조회를 줄이는 것이 목적입니다.
Running Pod도 의존 서비스, ingress/routing 또는 애플리케이션 오류로 사용자 요청을 처리하지 못할 수 있어,
관찰 사실과 원인 후보를 분리합니다. **증거가 부족하면 원인을 확정하지 않습니다.**

MODUI EKS 운영 경험에서 출발했으며, 코드에 MODUI 서비스 이름이나 endpoint를 내장하지 않았습니다.
현재 핵심은 **Rule/Correlation 기반 분석**입니다. LLM은 optional advisory이며,
FastAPI·외부 수집기·Discord adapter와 Docker/Helm 패키징 파일을 제공합니다.
구현된 interface와 실제 운영 연동 검증은 구분합니다.

## Architecture

```text
Kubernetes
     │
 ┌───┼─────────┐
 │   │         │
Events Metrics Logs
 │   │         │
 └───┼─────────┘
     ↓
Evidence Collector (Kubernetes / Prometheus / Loki)
     ↓
Normalized Evidence (source / timestamp / namespace / pod / container)
     ↓
Correlation Engine ← Rule Engine (기존 상태 탐지 유지)
     ↓
LLM Analyzer (optional, advisory, no tools)
     ↓
Structured Incident Report
     ↓
Terminal / JSON / Discord / FastAPI
```

## 핵심 기능

| 영역 | 구현 범위와 제약 |
|---|---|
| Kubernetes 증거 수집 | regular/init/ephemeral container, current/previous termination, readiness, memory limit 수집. Pod UID로 Event 연결, bounded pagination, timeout과 부분 실패 처리 |
| Prometheus Metrics | 5분 CPU rate, memory working set/limit, restart total/increase, waiting/terminated, phase/readiness. query별 실패를 분리하고 empty result를 장애로 해석하지 않음 |
| Loki Logs | namespace/pod/container 및 label mapping, 기본 최근 15분; collector에 incident_time을 명시하면 사건 전후 범위, line/response 제한. signal filtering → credential masking → snippet truncation 적용, 원본 로그 미저장 |
| 증거 상관 분석 | Pod/container 및 최근 20분 증거만 연결. high/medium/low confidence와 판단 근거 제공 |
| 선택적 LLM 분석 | provider abstraction, Responses API JSON schema 및 로컬 출력 검증. timeout/refusal 시 규칙 결과 유지 |
| Discord 알림 | 환경변수 webhook, 메시지 길이 제한, mention 차단, incident identity 기반 15분 dedup |
| FastAPI | namespace allowlist, optional bearer authentication, 단일 동시 분석, bounded memory store |
| 실행·연동 방식 | Snapshot, 명시적 bounded scheduled interface, 인증된 Alertmanager webhook interface |

## Safety Design

Kubernetes API에서는 pods/events 조회만 합니다. Secret 값, Pod env, AWS credential,
kubeconfig 내용은 수집하거나 출력하지 않습니다. memory limit만 Pod spec에서 선별합니다.
Kubernetes SDK의 기존 인증 경로 또는 in-cluster ServiceAccount를 사용합니다.
SDK의 EKS exec 인증은 기존 AWS 인증 플러그인 동작이며 API/LLM이 임의 명령을 받거나 실행하는 기능은 없습니다.
수집·분석 코드에는 subprocess/shell 실행 경로, 변경 API, remediation 기능이 없습니다.

로그/Event/LLM 출력은 마스킹하고 LLM에는 최대 40개 증거만 전달합니다.
LLM 결과는 별도 `llm_analysis` 필드에 남기고 규칙 category/confidence를 덮어쓰지 않습니다.
자동 마스킹은 모든 종류의 PII/secret을 보장하지 않으므로 외부 전송 정책 검토 후 활성화하세요.
`automatic_action_taken`은 항상 false입니다. 실제 운영 장애 주입/부하 테스트는 하지 않았습니다.

## Demo

Pod 상태만으로 설명하기 어려운 장애를 로그 증거와 연결하고, 원인 후보와 추가 검토 항목을
제시하는 두 대표 사례입니다. `examples.demo_incidents`는 7개 fixture의 장애 증거와
category/confidence를 재현하며 각 fixture의 예상 category 포함 여부를 검사합니다.

**fixture/mock 기반 오프라인 데모이며, 아래 `loki` 증거는 실제 Loki live query 결과가 아닙니다.**
Kubernetes 상태와 로그 모두 fixture에서 로드하며 실제 클러스터 연결이나 변경은 하지 않습니다.

```bash
.venv/bin/python -m examples.demo_incidents
.venv/bin/python -m examples.demo_incidents --format json
```

아래는 실제 `examples.demo_incidents` 터미널 출력을 핵심 evidence 중심으로 축약한 예시입니다.
타임스탬프, summary와 일부 상태 필드는 생략했습니다. 표시한 필드와 문구는 실행 결과와 같습니다.

```text
05_db_connection_refused: Kubernetes AIOps Incident Report | READ-ONLY
[critical] demo/demo-app DEPENDENCY_CONNECTION_FAILURE (medium)
  Confidence: CrashLoop과 DB 관련 refused 로그가 있으나 연결 대상의 실제 상태는 미확인입니다.
  loki error_signal=None postgres database connection refused db.internal:5432
  kubernetes state=waiting
  kubernetes reason=CrashLoopBackOff
  kubernetes ready=False
  Review: DB/service DNS, endpoint, 네트워크 정책과 의존 서비스 상태를 읽기 전용으로 확인하세요.

06_ingress_routing: Kubernetes AIOps Incident Report | READ-ONLY
[warning] demo/demo-app INGRESS_OR_ROUTING (low)
  Confidence: Running/ready와 routing 관련 5xx 로그만 확인했습니다. Service 상태와 원인 분리는 추가 조회가 필요합니다.
  loki error_signal=None upstream gateway HTTP 502 routing failed
  kubernetes phase=Running
  kubernetes state=running
  kubernetes ready=True
  Review: Ingress/Service 대상과 endpoint, upstream 로그를 확인하세요. 애플리케이션 자체 오류도 배제하지 마세요.
```

첫 사례는 CrashLoop과 DB 연결 거부 로그를 연결해 의존 서비스 장애 후보를 제시합니다.
두 번째는 Running/ready여도 요청 경로 장애 후보가 있을 수 있음을 보여주며, Service/Ingress를
검증하지 않았으므로 low confidence를 유지합니다. 두 사례 모두 확정 진단이나 자동 복구가 아닌
운영자의 추가 검토를 위한 결과입니다.

검증 범위는 아래 Testing / Validation 기록과 같습니다. Prometheus/Loki live endpoint와 실제 query는 미검증이며,
실제 LLM/Discord 호출과 Helm install은 수행하지 않았습니다. 이전 HOST build와 HTTP 200은 사용자 확인 상태이며 Docker unhealthy 해결 후 실제 runtime 검증은 대기 중입니다.
이전 실제 Kubernetes 검증은 read-only 조회 범위이며, **자동 복구(no auto-remediation)는 실행하지 않습니다.**

### Fixture categories

| Fixture | Expected category | Evidence |
|---|---|---|
| 01_crashloop | CrashLoopBackOff | 반복 종료 상태, 추가 원인 증거 부족 |
| 02_imagepull | IMAGE_PULL_FAILURE | image pull 상태 + Event |
| 03_oom | MEMORY_PRESSURE | OOM + 메모리 한도 90% 이상 |
| 04_high_cpu | HIGH_CPU | CPU rate + restart increase=0 |
| 05_db_connection_refused | DEPENDENCY_CONNECTION_FAILURE | CrashLoop + DB refused 로그 |
| 06_ingress_routing | INGRESS_OR_ROUTING | Running/ready + routing 5xx 로그, low confidence |
| 07_pending_scheduling | SCHEDULING_FAILURE | Pending + FailedScheduling |

추가로 HISTORICAL_RESTART_WARNING, Failed, Error, ErrImagePull, HighRestartCount를 지원합니다.
Ingress 후보는 실제 Service/Ingress 정상 상태를 검증한 확정 진단이 아닙니다.
현재 memory는 instant sample이므로 증가 추이나 OOM 발생 직전 peak를 주장하지 않습니다.
HIGH_CPU 임계값은 cores(기본 0.8)이며 CPU limit 대비 백분율이 아닙니다.

## Testing / Validation

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app tests examples scripts
.venv/bin/python -m pip check
.venv/bin/python scripts/security_scan.py
helm lint charts/aiops-engine
helm template demo charts/aiops-engine --namespace aiops
git diff --check
```

테스트는 외부 수집과 LLM/Discord를 mock 처리합니다. FastAPI는 native httpx ASGITransport로 검증합니다.
TestClient 정지 원인과 제한 환경의 테스트 loop 처리는 [검증 기록](docs/validation.md)에 설명합니다.
아래는 [검증 기록](docs/validation.md)에 남긴 범위이며, 실제 연동 전체의 성공을 의미하지 않습니다.

| 범위 | 검증 결과와 한계 |
|---|---|
| 로컬 테스트 | unittest 101개, pytest 101개/55 subtests PASS; native probe·HOST script·runtime 회귀 검증 포함. [최종 검증 기록](docs/validation.md) |
| 실제 Kubernetes | 최신 HOST READ-ONLY pods 조회는 command deadline 초과로 외부 connectivity 미확보. 이전 성공 이력은 [별도 이력](docs/validation-history.md)이며 현재 성공으로 간주하지 않음 |
| 외부 연동 | 최신 HOST Prometheus readiness 200, Loki HTTPError; 수정 후 live readiness는 HOST 재검증 대기. LLM/Discord live 미검증 |
| 실제 HTTP 서버 | HOST 이전 host/container `/health` HTTP 200 사용자 확인; 이번 수정은 ASGI 검증, 실제 Docker health는 대기 |
| 배포 | HOST 이전 build/HTTP 200 확인, Docker unhealthy 관찰. 최종 runtime은 HOST 검증 대기. Helm lint/template 정적 검증, 설치 없음 |

## Packaging

Python slim/non-root Dockerfile, healthcheck, allowlist Docker context를 제공합니다.
[Helm chart](charts/aiops-engine/README.md)는 Deployment/Service/ConfigMap/ServiceAccount와
namespace별 pods/events get/list Role/RoleBinding, probes/resources, hardened securityContext를 포함합니다.
Secret 자체, AWS 권한, ClusterRole은 포함하지 않습니다. **HOST에서 이전 build는 성공했으며, 최종 수정 image의 build/runtime은 HOST 검증 대기 중입니다. Helm install은 수행하지 않았습니다.**

## Tech Stack

Python 3.12 · Kubernetes Python Client · AWS EKS · Prometheus HTTP API · Loki HTTP API ·
FastAPI · LLM (OpenAI optional) · Discord · unittest/pytest · Docker · Helm.
DB와 observability 서버는 설치하지 않습니다.

## Quick Start

### 1. 개발 의존성 설치

Python 3.12와 virtualenv를 사용합니다. 새 checkout에서는 아래 순서로 준비합니다.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

### 2. 클러스터 없이 데모 실행

데모에는 클러스터 연결, 네트워크, credential이 필요하지 않습니다.

```bash
.venv/bin/python -m examples.demo_incidents
.venv/bin/python -m examples.demo_incidents --format json
```

### 3. Kubernetes snapshot 분석

기존 Kubernetes SDK 인증 경로와 조회 가능한 namespace가 필요합니다.

```bash
export AIOPS_ALLOWED_NAMESPACES=your-namespace
# 기존 MVP CLI (one snapshot)
.venv/bin/python -m app.main --namespace your-namespace
# 수집 → correlation → optional LLM/Discord
.venv/bin/python -m app.main --namespace your-namespace --structured
.venv/bin/python -m app.main --namespace your-namespace --format json
# 명시적 저장만 허용, 기존 파일 overwrite 거부
.venv/bin/python -m app.main --namespace your-namespace --format json --output /tmp/incident-report.json
```

기존 `--config config.example.yaml`, `--context`, `--restart-threshold`를 유지합니다.
CLI context/restart threshold는 옵션 또는 YAML로 지정하며 기본값은 current context/5입니다.
CLI 옵션이 YAML보다 우선하며 namespace는 환경 allowlist에 포함되어야 합니다. YAML은 `safe_load`와 키 검증을 사용합니다.
기존 상태 RuleEngine의 category 이름과 테스트는 유지됩니다. `--structured`/JSON은 correlation category를 사용합니다.
종료 코드: 0 분석 완료, 1 설정/Pod 조회 실패, 2 부분 증거 실패. 파일은 자동 저장하지 않습니다.

### 4. 선택적 외부 연동 설정

`.env.example`에는 변수 이름과 안전한 기본값만 있습니다. 프로그램은 `.env`를 자동 로딩하지 않습니다.
프로세스 환경 또는 운영 Secret 관리 도구로 전달하세요. API key와 webhook은 환경변수만 읽습니다.
`PROMETHEUS_URL`, `LOKI_URL`이 없으면 수집기는 비활성화됩니다.
LLM은 `AIOPS_LLM_ENABLED=true`, `OPENAI_MODEL`, `OPENAI_API_KEY`가 모두 필요합니다.
알림은 `AIOPS_NOTIFY_ENABLED=true`와 `DISCORD_WEBHOOK_URL`이 필요합니다.

## API

로컬 개발용 실행 예시입니다. 한 worker/replica를 사용합니다.

```bash
AIOPS_ALLOWED_NAMESPACES=your-namespace .venv/bin/uvicorn app.api:app --host 127.0.0.1 --port 8000 --workers 1
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"namespace":"your-namespace"}'
curl http://127.0.0.1:8000/api/incidents
```

`GET /api/incidents/{incident_id}`로 UUID 보고서를 조회합니다. `GET /health`는 로컬 liveness이며
Kubernetes/Prometheus/Loki 연결 성공을 보장하지 않습니다.
`AIOPS_API_TOKEN` 설정 시 `/api/*` 조회·분석에 bearer 인증을 요구합니다.
토큰 미설정은 로컬 개발 전용입니다. 외부 공개 전 인증/TLS/network 제한이 필요합니다.
API는 command, endpoint, path, kubeconfig 입력을 받지 않으며 추가 필드를 거부합니다.
최대 1,000개 incident를 메모리에 유지하며 재시작 시 사라집니다. 한 worker/replica를 사용합니다.

`POST /api/webhooks/alertmanager`는 `ALERTMANAGER_TOKEN` 설정 시에만 활성화되며
`X-Alertmanager-Token`과 최대 20개의 firing alerts에서 namespace만 검증해 새 증거를 수집합니다.
전달된 annotations를 사실/명령으로 사용하지 않습니다. 실제 Alertmanager 설정은 변경하지 않았습니다.
`app.scheduling.scheduled_analysis`는 iterations 1–1000, finite interval 최소 30초의 명시적 interface입니다.
import/API startup에는 시작하지 않습니다. SIGINT/SIGTERM은 다음 실행과 interval 대기를 취소합니다.
진행 중 동기 수집은 해당 요청 timeout까지 완료한 뒤 종료합니다. 예외는 마스킹된 warning으로 반환하고
다음 iteration을 유지합니다. 같은 엔진의 동시 실행은 거부합니다.

```bash
AIOPS_ALLOWED_NAMESPACES=your-namespace python -m app.scheduling \
  --namespace your-namespace --iterations 5 --interval 60
```

수집기에는 요청 timeout과 Kubernetes 30초/Prometheus 20초 collection deadline을 적용합니다.
Loki는 기본 5초, LLM 15초, Discord 5초입니다. LLM/notification은 분석당 최대 10개 incident에 적용하고
snapshot 분석 시작 후 60초가 지나면 추가 advisory를 시작하지 않습니다. 진행 중 요청은 자체 timeout까지
걸릴 수 있습니다. 전체 규칙 보고서는 보존합니다. 외부에서 주입한 adapter에도 유한 timeout이 필요합니다.
API POST body는 최대 64 KiB, 수신 timeout은 5초입니다.

## Repository structure

```text
app/         collectors, normalization, correlation/rules, reports, API/CLI/scheduler
             optional LLM/Discord, bounded store, HTTP transport, security/config
tests/       unit, offline ASGI integration, failure regression, seven fixtures
examples/    offline incident and legacy report demos
scripts/     source secret pattern scan, bounded HOST final validation
charts/      namespace-scoped Helm deployment
docs/        architecture, ADR, integration, security, audit and validation records
```

## Environment variables

`.env.example`은 변수 목록입니다. `.env`는 자동 로드하지 않습니다.

| Variable | Default / purpose |
|---|---|
| AIOPS_ALLOWED_NAMESPACES | default; comma-separated allowlist, CLI/API/scheduler 공통 |
| AIOPS_CLUSTER / AIOPS_CONTEXT | configured-context / current kubeconfig context; 보고서 identity / API·scheduler 인증 context |
| AIOPS_RESTART_THRESHOLD / AIOPS_CPU_THRESHOLD | 5 / 0.8 cores; API·scheduler 임계값 / structured CPU 임계값 |
| PROMETHEUS_URL / LOKI_URL | unset; 관리자가 신뢰하는 backend base URL만 설정 |
| LOKI_MINUTES / LOKI_LINE_LIMIT | 15 / 100; 1–1440 minutes / 1–1000 lines |
| AIOPS_LLM_ENABLED | false; optional advisory |
| OPENAI_MODEL / OPENAI_API_KEY | unset; 두 값 모두 필요, key는 Secret 환경으로 전달 |
| AIOPS_NOTIFY_ENABLED / DISCORD_WEBHOOK_URL | false / unset; webhook 설정과 enable 필요 |
| AIOPS_API_TOKEN / ALERTMANAGER_TOKEN | unset; API bearer / 별도 webhook authentication |

## Docker execution

```bash
docker build -t aiops-engine:1.0.0 .
docker run --rm --init --name aiops-local --read-only --cap-drop ALL \
  --security-opt no-new-privileges -p 127.0.0.1:8000:8000 \
  -e AIOPS_ALLOWED_NAMESPACES=default aiops-engine:1.0.0
curl http://127.0.0.1:8000/health
docker stop aiops-local
```

최종 HOST 검증: `bash scripts/final_host_validation.sh` ([판정 기준과 원인 분석](docs/host-validation.md)).
검증용 `aiops-final-health`만 교체하며 다른 컨테이너는 변경하지 않습니다.

이 async health는 Kubernetes 인증과 AnyIO worker thread를 요구하지 않습니다. 실제 분석에는 기존 인증이 필요합니다.
로컬에서 기존 kubeconfig를 read-only mount할 때 연결된 인증 파일/plugin도 관리해야 합니다.
slim image에는 AWS CLI가 없으므로 EKS exec kubeconfig는 별도 이미지/인증 준비가 필요합니다.
Secret·kubeconfig를 image에 COPY하지 않습니다. exec-form CMD가 Uvicorn에 종료 신호를 전달합니다.

## Helm deployment and Kubernetes READ-ONLY permissions

```bash
helm lint charts/aiops-engine
helm template aiops charts/aiops-engine --namespace aiops-test
# 검토한 이미지와 기존 isolated namespace가 준비된 환경에서만 실행
helm install aiops charts/aiops-engine --namespace aiops-test \
  --set image.repository=your-registry/aiops-engine --set image.tag=1.0.0
kubectl get pods -n aiops-test
```

이번 환경에서는 namespace 격리/접근을 확인할 수 없어 설치하지 않았습니다.
namespace별 Role은 core `pods`, `events`의 `get`, `list`만 허용합니다.
Secret, exec/logs, nodes, cluster role, 변경 verb를 부여하지 않습니다.
`allowedNamespaces`는 조회 대상과 RBAC scope를 함께 설정하며 namespace를 생성하지 않습니다.
`existingSecret`은 별도 관리하는 기존 Secret 이름입니다. chart values에는 Secret 값을 넣지 않습니다.

## Limitations

단일 worker/replica, 최대 1000건 memory store이며 재시작 시 incident/dedup 기록이 사라집니다.
Service/Ingress topology는 수집하지 않으며 routing은 로그 기반 후보입니다. metric/log Pod UID와
메모리 peak/time-series를 검증하지 않습니다. namespace 로그 제한 때문에 모든 workload coverage를
보장하지 않습니다. empty evidence/no findings는 정상 보장이 아닙니다.
Backend URL은 신뢰하는 운영 설정이며 API에서 URL을 받지 않습니다. private endpoint도 필요하므로
일반 사설 IP를 차단하지 않습니다. redirects와 URL credentials는 거부합니다. backend auth/tenant adapter,
PII 완전 탐지, dependency vulnerability/SBOM scan과 실제 배포/외부 연동 검증은 남아 있습니다.

## Documentation

[Architecture](docs/architecture.md) · [ADR](docs/adr/001-read-only-design.md) ·
[Configuration and integration](docs/integration.md) · [Security](docs/security.md) ·
[Portfolio](docs/portfolio.md) · [Interview](docs/interview.md) · [Validation](docs/validation.md)

## Future Work

memory/restart time-series, Pod UID와 metric/log identity 강화, Service/Ingress read-only evidence,
backend 인증/tenant 지원, shared persistent incident store, distributed dedup/cooldown,
지속 감시 queue/rate limits, ground-truth 기반 rule/LLM evaluation을 우선합니다.
자동복구는 별도의 정책·승인·감사 설계 전에는 추가하지 않습니다.
