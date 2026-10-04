# HOST validation 재조사 — 2026-10-04

최신 HOST 실제 결과: build/running/HTTP 200 PASS, health latency max 1.7996s,
mean 0.6839s, zombie 12회 모두 0. Docker health는 unhealthy, history exit -1/-1/1/-1.
CPU는 대부분 0.x%이나 374.81%/56.29%의 순간값, PIDS는 대부분 2이나 3/7.
Prometheus 200, Loki HTTPError, Kubernetes read-only 조회 deadline 초과.
이 결과는 전체 FAIL이며 Docker healthy를 확인하지 못했다. 이 수정 후의 Docker
build/runtime은 sandbox에서 수행하지 않았다. HOST 재실행 전에는 PASS를 주장하지 않는다.

## 확인된 코드와 미확정 원인

- 예전 shell-form `python -c` HEALTHCHECK는 Docker의 `CMD-SHELL`이 되고 shell과
  interpreter가 시작된다. 유효한 JSON exec-form은 `CMD`여야 한다. 조사 시작 시
  working tree에는 이미 JSON `python -S` 형식이 있었다. 따라서 HOST의 CMD-SHELL이
  현재 파일에서 자동 변환됐다고 단정할 수 없다. 이전 image/container, 다른 build
  context, 잘못된 quoting 등은 실제 inspect가 필요하다. 지금은 단일 줄 exec-form을
  사용하고 **image와 container의 Config.Healthcheck.Test**를 모두 검사한다.
  image가 `['CMD', '/usr/local/bin/aiops-healthcheck']`가 아니면 교체 전에 FAIL한다.
- Python은 `-S`여도 interpreter와 stdlib 모듈을 매번 초기화한다. urllib에는 HTTP,
  TLS, URL/proxy 등의 추가 imports가 있다. 이전 http.client 대체 역시 Python imports가
  필요했다. HTTP latency는 HTTP 요청 이후를 측정하며 Docker의 전체 exec/startup 시간을
  측정하지 않는다. 빠른 HOST HTTP는 느린 Docker exec/startup과 양립한다.
- 현재 Docker probe는 별도 build stage에서 컴파일한 작은 C 실행 파일이다. compiler는
  runtime image에 없다. shell/Python/import/DNS/proxy/자식 프로세스 없이 IPv4 loopback
  8000의 `/health`에 HTTP/1.0 close 요청을 보낸다. HTTP 200과 현재 정확한 compact payload를
  검사하고 응답은 4096 bytes 이내, process 전체 I/O alarm은 2초이다. partial send/read,
  socket error, malformed/oversized body는 실패한다. Docker timeout은 **3초 그대로**다.
  30초 interval, 10초 start period, retries 3도 유지한다. OS가 프로브를 스케줄하지 못하는
  현상은 native probe나 async endpoint만으로 보장할 수 없다.
- `/health`는 조사 시작 시 이미 `async def`였다. 이를 유지한다. constant dict 반환은
  blocking I/O가 없어 적절하며 AnyIO worker capacity를 사용하지 않는다. threadpool을
  모두 점유한 회귀 테스트에서도 반환한다. 예전 sync endpoint의 threadpool 비용을
  이번 HOST timeout의 확정 원인으로 재사용하지 않는다.
- Uvicorn은 exec CMD, workers=1, reload 없음. app startup은 scheduler/collector/process
  pool을 시작하지 않는다. init + uvicorn이 idle의 2 task와 부합한다. Docker healthcheck는
  반드시 일시적 프로세스를 생성한다. Docker PIDS는 프로세스뿐 아니라 thread도 포함한다.
  PIDS 3은 프로브와 양립하지만 7의 정확한 task 구성은 과거 샘플만으로 알 수 없다.
  zombie 0과 PIDS의 원래 값 복귀는 leak 확정 근거가 아니다.
- upstream runc exec 구현은 실행 task를 container cgroup에 넣으며, exec 전에 Go runtime
  초기화와 thread 생성이 발생할 수 있다. `runc:[2:INIT]`라는 중간 실행 상태도 있다.
  따라서 Python single-threaded imports만으로 374%를 설명하지 않는다. runc 초기화,
  application threads, 통계 구간 문제를 별도로 대조해야 한다. HOST runtime/version/task
  정보가 없어 **이번 spike가 runc 때문이라는 것은 가설**이다. native probe는 interpreter
  비용을 제거하지만 Docker/runc exec 비용 자체를 제거하지 않는다.
  근거: [runc setns/cgroup source](https://github.com/opencontainers/runc/blob/main/libcontainer/process_linux.go),
  [runc namespace init source](https://github.com/opencontainers/runc/blob/main/libcontainer/nsenter/nsexec.c),
  [upstream Go init thread 설명](https://github.com/opencontainers/runc/issues/1914).

근거: [Dockerfile HEALTHCHECK](https://docs.docker.com/reference/dockerfile/#healthcheck),
[Docker stats PIDS/threads](https://docs.docker.com/reference/cli/docker/container/stats/),
[FastAPI sync route threadpool](https://fastapi.tiangolo.com/async/#path-operation-functions).

## 측정 변경의 이유와 한계

예전 `docker stats --no-stream` 12개의 값은 각 CLI의 Docker 통계 구간이며 측정하려던
5초 idle 구간의 누적 CPU 사용량이 아니다. 또한 PIDS range <=4는 정상 프로브/스레드의
identity/lifecycle을 구별하지 않는다. 이를 사용해 application busy loop/leak을 확정할 수 없다.
Docker CLI와 validation subprocess는 HOST에서 실행돼 컨테이너 cgroup CPU/PIDS에 직접
포함되지 않지만 HOST 경쟁 부하를 만들 수 있고 HTTP health 요청은 앱의 작업을 만든다.

새 측정은 HOST cgroup-v2 `cpu.stat`, `pids.current`, `cgroup.procs`와 `/proc/PID/task/*/stat`을
읽는다. 컨테이너 exec, 추가 sampling subprocess, docker stats 프로세스를 만들지 않는다.
컨테이너의 초기 init/uvicorn 2 task의 starttime과 identity를 고정한다. 프로브가 baseline에
걸리면 최대 3초만 종료를 관찰하고, 알 수 없는 task를 baseline으로 인정하지 않는다.
12개 약 5초 구간마다 0.5초 snapshot을 출력하며:

- CPU는 monotonic elapsed와 cgroup cumulative usage delta로 계산한다. **구간 max <50%,
  전체 시간 가중 mean <10%** 제한을 유지한다. 0.5초별 CPU도 출력하므로 짧은 burst를
  지우지 않는다. 5초 workload stability와 subsecond burst는 서로 다른 지표다.
- 모든 CPU에 probe와 HOST HTTP 요청 처리도 포함한다. 살아 있는 task별 CPU ticks와
  monotonic/epoch 시각, Docker probe Start/End/ExitCode로 원인을 대조할 수 있다.
  executable path도 읽되 argv/environment/credentials는 읽지 않는다.
  0.5초 사이 종료된 task의 CPU는 cgroup 총량에 남지만 task별 attribution은 불완전하다.
  샘플만으로 해당 burst를 probe 원인이라고 확정하지 않는다.
- baseline task 교체/종료, 알 수 없는 추가 thread/process, 동시에 두 개 이상 native probe,
  zombie는 FAIL이다. 정상 native probe 한 개 또는 실제 executable이 runc/docker-runc이고
  comm이 `runc:[2:INIT]`인 **단일 runtime init process의 threads**만 허용한다. task/PIDS
  총량은 기존 absolute ceiling 32 이하이고 task별 관측 identity가 이를 설명해야 한다.
  해당 PID/starttime이 처음 관측된 뒤 3초 이상 지속되면 FAIL하며 사라져야 한다. 이름만
  runc처럼 보이는 다른 executable은 거부한다. 이것은 수치 range 완화가 아니라 알려진
  생성/exec/종료 수명과 identity 검사다. PIDS 7도 실제 runtime identity가 확인돼야 허용한다.
  프로브가 종료하지 않으면 Docker timeout/health 검사에서도 FAIL한다.
- HOST cgroup-v2 또는 `/proc`를 읽을 수 없으면 검증은 non-zero로 종료하고 PASS를 만들지
  않는다. 0.5초 사이의 모든 task 생성을 증명하는 tracing은 아니며 장기 soak test도 아니다.
- 모든 HTTP는 정확한 payload/200, max latency <2s를 요구한다. Docker healthy bounded wait와
  sampling 후 healthy를 모두 요구한다. 전체 출력 없이 healthy를 주장할 수 없다.

## 외부 서비스와 exit status

Loki `grafana/loki:2.9.0`의 HOST mapping `127.0.0.1:3300 -> 3100`에 맞춰
`http://127.0.0.1:3300/ready`를 유지한다. HTTPError의 실제 status와 최대 1024 bytes의
readiness body를 마스킹·JSON escaping 후 출력한다. 503 starting/not-ready, connection
failure 등은 **external NOT AVAILABLE**이다. 서비스가 살아 있어도 readiness 200이 아니면
PASS가 아니다. Prometheus 역시 외부 readiness evidence를 구분한다. monitoring container의
설정 변경/재시작/로그 전체 출력은 하지 않는다.

Kubernetes는 local current-context/config view와 remote GET pods만 실행한다. 8초 request
limit, auth plugin을 포함한 20초 process-group deadline을 유지한다. timeout/auth/network
failure는 external NOT AVAILABLE이며 application 코드 실패로 취급하지 않는다. 인증/오류
원문은 출력하지 않는다. apply/patch/delete/exec/install 등 write는 없다.

`exec python3`가 Python의 exit status를 Bash script의 status로 전달한다. 전체 결과에 FAIL이
하나라도 있으면 1, FAIL은 없지만 NOT AVAILABLE/NOT CONFIGURED가 있으면 2, 전부 PASS일
때만 0이다. 마지막 `SCRIPT EXIT CODE`도 명시한다. shell+tee 경계 회귀 테스트는 실제 Bash
script에 실패를 주입해 script=1/tee=0을 확인한다. 예전 코드도 sys.exit(1)이 있었으므로
HOST 마지막 0은 pipeline의 tee status 또는 후속 echo 등의 `$?`였을 가능성이 높다.
과거 실행 wrapper가 없으므로 이를 확정 원인으로 단정하지 않는다.

## HOST 재실행 (프로젝트 root에서 한 명령)

```bash
bash -c 'set -o pipefail; bash scripts/final_host_validation.sh 2>&1 | tee /tmp/aiops-final-host-validation.log; codes=("${PIPESTATUS[@]}"); printf "SCRIPT EXIT CODE: %s; TEE EXIT CODE: %s\n" "${codes[0]}" "${codes[1]}"; if (( codes[0] != 0 )); then exit "${codes[0]}"; fi; exit "${codes[1]}"'
```

`PIPESTATUS`를 pipeline 직후 배열로 저장한다. echo/printf를 먼저 실행하면 증거가 덮인다.
이 명령은 script 실패 status를 그대로 반환하고 script 성공 시 logging 실패도 반환한다.

HOST Python3, Docker access, cgroup-v2 accounting read 권한이 필요하다. namespace는 default,
필요하면 `AIOPS_VALIDATION_NAMESPACE` 환경 변수로 지정한다. 지정된 image tag만 build하고
`aiops-final-health`의 검사된 정확한 ID만 교체한다. 예상치 않은 image나 Compose/Swarm
managed target은 거부한다. 다른 container identity/start time/state는 실패 경로에서도
비교한다. validation container는 inspection용으로 남긴다. MODUI/monitoring containers,
production resources, Kubernetes resources, Git commit/push/tag는 수정하지 않는다.
