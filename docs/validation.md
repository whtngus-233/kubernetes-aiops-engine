# Validation record — 2026-10-03 UTC

## Audit and scope

기존 MVP 14개 unittest가 먼저 통과했다. 시작 시 소스 파일은 모두 untracked였다.
코드/테스트를 유지하며 확장했다. Ubuntu/Python 3.12 기존 virtualenv를 사용했다.
초기 MVP 기록에는 pytest 설치 실패와 EKS timeout이 있었지만 이번 확장 실행에서는
제한 밖 패키지 설치와 일부 READ-ONLY EKS 조회가 성공했다. 이전 결과를 현재 결과로 혼동하지 않는다.

## Local checks

- `python -m unittest discover -s tests -q`: **69 tests passed**, 기존 14개 포함.
- `python -m pytest -q`: **69 passed, 31 subtests passed**, 61.60초. Starlette TestClient deprecation warning 1개.
- `python -m compileall -q app tests examples scripts`: 성공.
- `python -m pip check`: No broken requirements found.
- `python scripts/security_scan.py`: source allowlist secret pattern scan 통과. heuristic이지 전수 보장은 아니다.
- `git diff --check`: 성공. 소스가 untracked이므로 별도 whitespace scan도 수행했다.
- `python -m examples.demo_incidents --format json`: 7개 fixture의 expected category가 모두 일치.
- `python -m examples.mock_report`: 기존 터미널 데모 성공.
- `helm lint charts/aiops-engine`: 1 chart linted, 0 failed. 선택 사항인 icon recommendation만 표시.
- `helm template` default namespace 및 team-a/team-b 설정 렌더링 성공.
- rendered YAML parse/RBAC 검사: default 6개 리소스, Secret/ClusterRole 없음,
  Role resources=pods/events, verbs=get/list 확인.
- 앱 소스의 unsafe subprocess/shell/mutation/YAML loading 패턴 검색 결과 없음.

## Test environment limitations

샌드박스에서 FastAPI TestClient의 asyncio thread portal이 대기했다. 진단 stack에서 selector/future wait를 확인했다.
제한 밖 mock tests에서는 정상 완료됐다. 한 번의 60초 제한 pytest는 3개 테스트 후 timeout되어 통과로 간주하지 않았다.
최종 unittest/pytest는 테스트가 실제 완료된 결과만 기록한다. 반복 대기하던 로컬 테스트 프로세스는 중단했다.
Starlette 1.7.0은 httpx TestClient fallback deprecation warning을 낸다. 현재 동작은 테스트로 확인하지만
향후 httpx2 dev adapter migration을 검토해야 한다.
패키지 설치는 처음 sandbox DNS 실패 후 허용된 재시도에서 성공했다.

## Actual Kubernetes READ-ONLY checks

현재 context 이름 확인: modui-eks를 가리키는 기존 EKS context (kubeconfig 내용 출력 없음).
`kubectl get pods -n modui-prod`에서 **11개 Pod가 Running**으로 조회됐다.
확장 CLI `python -m app.main --namespace modui-prod --structured`는 **exit 0**으로 완료했고
configured rule findings가 없었다. 경고 없는 snapshot 결과이며 실제 서비스 전체 정상 판정은 아니다.
조회된 Pod/metric/log/Event 원본을 fixture나 Git 파일로 저장하지 않았다.

연결은 불안정했다. sandbox 및 일부 제한 밖 services/namespaces/cluster-wide pods 조회는
10/15초 request timeout으로 실패했다. 연속 무제한 retry는 하지 않았다.
Kubernetes SDK 재시도는 0으로 설정했다. Pod/Event client collection은 bounded pagination과 timeout을 사용한다.

## Prometheus / Grafana / Loki discovery

EndpointSlice 전체 이름 조회가 한 번 성공했고 modui-prod의 grafana-proxy 및 앱 endpoint names를 확인했다.
modui-prod Pod 조회에서도 grafana-proxy Pod가 확인됐다. 이것은 Grafana/Prometheus/Loki backend의
존재나 query 성공을 증명하지 않는다. Services/Namespaces/전체 Pod 조사 일부가 timeout되어
Prometheus, kube-state-metrics, node-exporter와 Loki의 설치 여부는 **미확인**이다.
안전한 backend query endpoint를 확인하지 못해 실제 Prometheus/Loki query는 수행하지 않았다.
설치/배포/port-forward/proxy 권한 변경 없이 코드·mock tests·설정·향후 연결 문서를 제공했다.

## LLM / Discord / FastAPI

LLM: disabled, provider success/malformed/timeout/incomplete, structured JSON, no tools,
output sanitize/limit을 mock으로 검증했다. 실제 API key 조회·출력/외부 LLM 호출은 하지 않았다.
LLM 결과는 rule category/confidence를 덮어쓰지 않는다.
Discord: disabled, successful delivery/duplicate, failure retry, invalid endpoint를 mock 검증했다.
실제 webhook 메시지는 보내지 않았다.
FastAPI: health, analyze/retrieval, allowlist/extra command rejection, IDs, auth,
collector failure, concurrency 429, authenticated/disabled webhook을 local TestClient로 검증했다.
실제 API 서버를 운영 환경에 배포하거나 공개하지 않았다.

## Packaging / Git / safety

Dockerfile 작성과 source/static 검토만 했다. **Docker build는 실행하지 않았다.**
Helm lint/template/static 검사만 했다. **Helm install/upgrade/uninstall을 실행하지 않았다.**
EKS/AWS/DB/MODUI application 변경, Secret 조회, workload fault injection, 트래픽 부하 테스트는 없었다.
Git add/commit/push 및 remote 변경은 하지 않았다. .venv/cache/credentials/env는 Git/Docker 제외 대상이다.

## Before deployment

접근 가능한 기존 Prometheus/Loki와 실제 label/metric/auth/tenant 정책 확인,
운영자의 Secret provision 및 API token/TLS/network policy, 이미지 build/vulnerability/SBOM scan,
reviewed chart values/RBAC, real integration tests가 필요하다.
한 worker/replica와 메모리 store의 데이터 손실/재시작 dedup reset을 먼저 수용하거나 shared store를 구현한다.
