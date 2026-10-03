# Security review

수집 구현에서 Kubernetes GET/list만 사용합니다. chart는 namespace별 pods/events get/list만 부여합니다.
Secret API, logs/exec, services/proxy, nodes, AWS resource 권한은 없습니다.
클러스터 조사 명령은 get/context name 수준으로만 실행했습니다.

API에는 namespace 외 command/URL/path 입력이 없고 pydantic extra=forbid, namespace pattern/allowlist,
UUID retrieval와 제한된 store를 적용했습니다. YAML safe_load, explicit output(x mode), bounded HTTP response,
redirect 거부, env proxy 비활성화, network timeout으로 입력과 외부 경계를 제한합니다.
기존 kubeconfig exec 인증 플러그인은 사용자 인증 환경의 SDK 동작이며 앱에는 shell/subprocess 경로가 없습니다.

Authorization/Bearer/Basic, api key/password/secret/token/cookie, URL credentials, AWS access ID,
OpenAI key/JWT/private-key 형태, Discord webhook을 sanitize합니다. Event/로그/structured reports,
LLM input/output와 Discord 전송 경로에 적용합니다. 외부 오류 텍스트를 출력하지 않습니다.
PII, 서비스 내부 hostname, 임의 custom credential은 완전 탐지가 불가능합니다.
규칙은 정규식 기반 heuristic이며 LLM 전송 전 운영 데이터 정책을 검토해야 합니다.

`.gitignore`는 .venv/.env/.aws/.kube/kubeconfig/key/cache/reports를 제외합니다.
`.env.example`만 허용하며 실값은 없습니다. Docker build context는 app/requirements만 allowlist합니다.
Secret pattern scanner는 소스 디렉터리만 검사하며 credential/.env/kubeconfig 내용을 읽거나 출력하지 않습니다.
테스트의 `fake-*`는 mock sentinel입니다. scanner는 값 대신 파일/행 번호만 표시합니다.

API bearer 미설정은 로컬 개발 전용입니다. 운영은 AIOPS_API_TOKEN/TLS와 네트워크 접근 제한을 적용하세요.
Webhook은 별도 token mandatory, 알림은 mention disabled입니다. chart는 non-root, read-only filesystem,
drop ALL, seccomp RuntimeDefault를 적용합니다. healthcheck는 backend 연결 확인 기능이 아닙니다.

남은 한계: 인증 backend adapters, distributed rate limiting, request byte limit, dependency vulnerability/SBOM scan,
PII policy, 중앙 감사 저장소. dependency check는 호환성 검사이며 vulnerability 검사가 아닙니다.
