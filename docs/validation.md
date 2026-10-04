# HOST 결과 반영 재검증 — 2026-10-04 UTC

기존 dirty working tree를 보존했다. Docker 명령, Kubernetes write, production 수정,
Git commit/push/tag는 실행하지 않았다. 이번 수정 후 Docker runtime healthy는 HOST에서
아직 확인되지 않았다. 최신 실제 HOST 결과는 전체 FAIL이며 해당 증거를 보존한다.

| Check | 이번 수정 후 실제 결과 |
|---|---|
| compileall app/tests/examples/scripts | PASS |
| native C probe compile (-Os -Wall -Wextra -Werror) | PASS |
| full unittest | PASS: 101 tests, 61.999s |
| full pytest | PASS: 101 passed, 55 subtests passed, 131.30s |
| Integration/failure/health/HOST/runtime/native regression | PASS: 31 passed, 24 subtests passed, 85.80s |
| Seven terminal/JSON demos + legacy mock_report | PASS: 7 categories, JSON/fixture parse, automatic_action_taken=false |
| Source security scan | PASS: 79 allowlisted source files, C 포함; heuristic only |
| pip check | PASS: No broken requirements found |
| git diff --check | PASS |
| Helm lint | PASS: 1 chart, 0 failures; optional icon INFO |
| Helm template / RBAC | PASS: default/2 namespace YAML; pods/events get/list Role만, ClusterRole/Secret 없음 |
| HOST script bash -n / embedded Python compile | PASS |
| shellcheck | NOT AVAILABLE: executable 미설치; 실행 성공을 주장하지 않음 |
| Docker build/runtime after this revision | PENDING HOST: sandbox에서 실행하지 않음 |
| Latest operator HOST Docker result before this revision | build/running/HTTP 200 PASS; health unhealthy, overall FAIL |
| Latest operator CPU / PIDS / zombies | mostly 0.x%, spikes 374.81/56.29%; PIDS 2/3/7; zombies all 0 |
| Latest operator external readiness | Prometheus 200; Loki HTTPError; Kubernetes GET deadline exceeded |
| Other containers / production / Kubernetes writes | 이 환경에서 변경 없음; HOST script는 다른 container snapshot 비교 |
| Git commit/push/tag | 실행하지 않음 |

단일 native exec probe로 Python/urllib/import/shell 비용을 제거했다. HEALTHCHECK의 실제
CMD 배열을 image/container inspect로 검사하고 timeout은 3초 유지한다. `/health`는 이미
async였으며 유지했다. CPU는 cgroup 누적량/elapsed, PIDS는 identity/lifetime과 runc init
threads를 관찰한다. FAIL/non-availability는 각각 exit 1/2이고 Bash+tee 회귀 검증을 한다.
외부 Loki status/안전한 body와 Kubernetes timeout을 application 실패와 분리한다.

실제 spike/timeout의 최종 원인은 HOST 시각별 task/runtime 증거가 필요하다. runc startup은
upstream 근거가 있는 후보이며 이번 HOST 원인으로 확정한 것은 아니다.
[상세 조사·측정 기준·단일 HOST 실행 명령](host-validation.md)을 참고한다.

추가 legacy demo 실행 중 존재하지 않는 `examples.demo` 모듈을 잘못 지정해 실패했고,
실제 `examples.mock_report`로 교정해 실행했다. 테스트 삭제/skip은 없다.

---

# Earlier engineering baseline validation — historical record

아래는 이번 health 수정 이전 단계의 기록이며 현재 HOST 상태 또는 이번 실행 결과를 뜻하지 않는다. 이전 포트폴리오 작업과 최초 EKS 성공 기록은
[validation-history.md](validation-history.md)에 보존하며 이번 성공으로 계산하지 않는다.
시작 working tree는 clean, HEAD는 `4ae4853`이었다. credential 생성/출력, cluster mutation,
자동복구, 운영 장애 주입, sandbox 우회는 수행하지 않았다.

| Check | Actual result |
|---|---|
| compileall app/tests/examples/scripts | PASS |
| python -m unittest discover -s tests -v | PASS: 82 tests, 11.196 seconds |
| pytest -q | PASS: 82 passed, 38 subtests passed, 32.60 seconds |
| Offline API pipeline integration | PASS: 별도 integration 실행 2 passed (27.30 seconds); 실제 engine/normalization/correlation/API/store 사용 |
| python -m examples.demo_incidents | PASS: 7 fixture categories |
| python -m examples.demo_incidents --format json | PASS: 7 fixture categories, JSON parse 확인 |
| scripts/security_scan.py | PASS: heuristic source secret scan |
| pip check | PASS: No broken requirements found |
| Docker build -t aiops-engine:1.0.0 . | FAIL: Docker API unix socket permission denied; image 생성 불가 |
| Docker runtime health | NOT AVAILABLE: build가 실패하여 실행할 image 없음 |
| helm lint charts/aiops-engine | PASS: 1 chart, 0 failures (optional icon INFO) |
| helm template demo charts/aiops-engine --namespace aiops | PASS: YAML/RBAC 정적 검사 포함 |
| Isolated Helm install | 실행하지 않음: isolated namespace의 접근·안전성 확인 불가 |
| kubectl get pods / get namespaces --request-timeout=8s | 접근 완료하지 못함; namespaces 조회 전체 60초 timeout, exit 124 |
| Actual KubernetesCollector default namespace | FAIL: sanitized Pod 조회 실패, exit 1; 현재 READ-ONLY 연동 NOT AVAILABLE |
| Uvicorn app.api:app process | startup와 shutdown 완료; loopback bind 거부로 실제 HTTP health/분석 성공 미검증 |
| curl localhost health | 연결 실패 (exit 7), 성공으로 간주하지 않음 |
| Prometheus / Loki | endpoint 미설정; live NOT AVAILABLE, mock timeout/empty/malformed/partial failure PASS |
| LLM advisory | model/enable 미설정, live NOT CONFIGURED; key 없음/timeout/invalid JSON/schema/unexpected response fallback PASS |
| Discord | webhook/enable 미설정, live NOT CONFIGURED; disabled/timeout/error/dedup/masking mock PASS |
| Scheduler | bounds/cancellation/errors/recovery/overlap PASS; invalid CLI bounds exit 2 |
| git diff --check | PASS |

## TestClient 정지 원인과 변경 이유

요청받은 기존 전체 unittest를 먼저 실행했고 첫 API 테스트에서 90초 timeout을 재현했다.
기존 `pytest -q`는 별도로 `ModuleNotFoundError: app` 수집 실패를 보였다. `pytest.ini`에
repository pythonpath를 지정해 console pytest와 python -m pytest의 import 동작을 일치시켰다.

앱을 제외한 `TestClient(FastAPI()).get('/')`도 대기했다. faulthandler 스택은 호출 스레드의
AnyIO `run_sync_from_thread`/Future wait와 portal 스레드의 asyncio selector wait를 보여줬다.
독립 socketpair probe의 `send()`는 `PermissionError`, errno 1 (EPERM)이었다.
독립 asyncio.to_thread는 결과 42를 받았지만 runner shutdown의 스레드 wakeup에서 대기했다.
따라서 수집기 네트워크, DB, scheduler lifecycle 또는 app import side effect가 필요 없는
환경 제한 재현을 확보했다. 이전 schema 생성 중 segfault 기록은 재현되지 않았으며
새 검증에서 segmentation fault가 없었다. 과거 segfault 자체의 원인을 확정했다는 뜻은 아니다.

API 테스트를 `unittest.IsolatedAsyncioTestCase`와 httpx.AsyncClient/ASGITransport로 전환했다.
Python 3.12용 Runner factory는 socketpair send가 EPERM인 경우에만 selector wait를 최대 10ms로
제한해 cross-thread callback을 처리한다. 정상 환경에서는 표준 event loop를 사용한다.
운영 앱/의존성/endpoint/worker를 monkeypatch하지 않고 테스트 harness에만 적용했다.
테스트 삭제/skip은 없으며 validation/auth/allowlist/429/webhook/조회 assertion을 유지했다.
모든 client를 닫으며 concurrent test task를 회수한다. FastAPI lifecycle은 자동 scheduler나
외부 호출을 시작하지 않는다. 실제 socket HTTP는 별도 시도했고 환경 때문에 실패한 것으로 기록한다.

검증 환경: Python 3.12, FastAPI 0.142.2, Starlette 1.7.0, httpx 0.28.1,
AnyIO 4.15.1, Pydantic 2.13.5. 기존 패키지 변경/credential 우회 없이 검증했다.

## Failure coverage와 시간 제한

CrashLoop/ImagePull/OOM/High CPU/DB refused/routing/Pending fixtures, empty/conflicting/stale/cross-workload
증거, source timeout/unavailable/malformed/partial failure, LLM invalid JSON/schema/unexpected response,
Discord 실패, scheduler 취소/오류 복구를 offline 검증했다. 규칙 원인 미확정과 automatic_action_taken=false를 유지한다.

Kubernetes 30초 collection deadline/100 pages/500 items, Prometheus 20초 collection deadline/
query별 10000 samples, HTTP response 2MB, Loki 1–1000 lines와 1–1440분 제한을 적용한다.
요청 자체 timeout과 단계 deadline은 강제 thread kill이 아닌 cooperative bounds다.
진행 중 요청은 자체 connect/read timeout까지 걸릴 수 있고 kubeconfig exec 인증 plugin과 custom adapter는
해당 환경의 자체 bounded execution이 필요하다. LLM/Discord는 최대 10 incidents와 60초 advisory 시작
budget을 적용하며 규칙 보고서는 삭제하지 않는다. stop_event/SIGTERM은 interval과 다음 실행을
취소하고 진행 중 수집은 timeout 내 반환 후 종료한다. 분산 lock은 없다.

## 남은 실제 검증

접근 가능한 Docker daemon에서 build/runtime health, network가 허용된 환경에서 실제 API HTTP,
조회 가능한 Kubernetes와 isolated namespace, 기존 Prometheus/Loki backend/labels/auth,
설정된 LLM model과 Discord의 live integration이 필요하다. dependency vulnerability/SBOM scan,
Service/Ingress topology, metric/log UID, time-series, persistent/shared store는 미구현이다.

## Final Git outcome

`git add`와 요청된 `git commit -m 'feat: finalize aiops engineering baseline'`을 시도했으나
`.git/index.lock`: Read-only file system으로 모두 exit 128이다. 새 commit은 생성되지 않았고
변경 파일은 workspace에 유지된다. 원격 tag 조회는 github.com DNS 실패 (exit 128)였다.
새 commit을 만들 수 없으므로 기존 HEAD에 v1.0.0을 붙이지 않았다. Git 제한을 우회하지 않았다.
`git push origin main`도 실제 시도했으며 github.com DNS 실패로 exit 128이다.
