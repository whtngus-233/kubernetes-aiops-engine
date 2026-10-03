# Configuration and safe integration

변수 목록은 `.env.example`을 참고하세요. CLI YAML은 namespace/context/restart_threshold만 받습니다.
프로세스 환경으로 선택 collector 설정을 분리하며 .env 자동 로딩은 하지 않습니다.
다른 Kubernetes에서 namespace/context/cluster/backend endpoint만 바꾸면 재사용할 수 있습니다.

## Kubernetes

로컬 SDK는 현재 kubeconfig context, 클러스터 내부는 ServiceAccount를 사용합니다.
pods/events list만 필수이며 chart는 get/list만 허용합니다. Pod spec에서 memory limit만 읽고
Secret/env 값을 조회하지 않습니다. local EKS exec authentication에는 기존 AWS CLI 인증 환경이 필요하며
slim image는 AWS CLI/credential을 제공하지 않습니다. runtime credential mount는 별도 검토 대상입니다.

## Prometheus

기존 안전한 endpoint를 `PROMETHEUS_URL`로 설정합니다. instant `/api/v1/query`만 호출합니다.
cAdvisor CPU/memory와 kube-state-metrics status/resource limits가 필요합니다.
CPU는 sum by namespace/pod/container rate[5m], restart increase[5m]이며 default label 이름은 고정입니다.
metric 이름/label이 다른 backend는 query mapping 변경이 필요합니다. collector는 node-exporter를 요구하지 않습니다.
node-exporter는 노드 분석 확장에 사용할 수 있습니다. Grafana 자체는 metrics 저장소가 아닙니다.
empty/missing series는 unknown입니다. threshold는 cores이며 namespace마다 workload에 맞게 조정하세요.

## Loki

기존 endpoint를 `LOKI_URL`로 설정합니다. `/loki/api/v1/query_range` GET만 사용합니다.
기본 namespace/pod/container label입니다. 다른 배포에서는 LokiCollector label constructor를 바꿔 연결하세요.
LOKI_MINUTES 1–1440, LOKI_LINE_LIMIT 1–1000. incident_time을 주면 사건 전후 bounded window를 사용합니다.
namespace 전체 최신 N줄이므로 모든 Pod 로그 coverage를 보장하지 않습니다.
Raw logs는 HTTP 응답에서만 일시 처리하며 signal만 sanitize/truncate해서 evidence로 유지합니다.
PII 및 앱 고유 secret 패턴은 별도 검토하세요.

## Network and backend authentication

새 observability 서버를 배포하지 않습니다. port-forward, 공개 endpoint 생성도 수행하지 않았습니다.
가능하면 기존 사설/인클러스터 endpoint를 사용하세요. 현재 transport는 TLS verification을 유지하며
redirect를 따라가지 않고 credential-bearing URL을 거부합니다. bearer/basic/tenant headers와
Kubernetes API service proxy transport는 이번 구현에 포함하지 않았습니다. 인증 backend는 별도 transport
adapter를 주입해 구현할 수 있습니다. Secret 값을 URL/YAML/Git에 넣지 마세요.

## LLM and Discord

OpenAI 모델은 운영자가 `OPENAI_MODEL`로 선택합니다. API key 없으면 자동 disabled입니다.
설정된 모델이 structured outputs를 지원하는지 실제 연결 전 확인하세요.
[공식 OpenAI Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs)를 바탕으로
Responses API `text.format` JSON schema를 사용합니다. store=false, no tools, max output 1200 tokens.
실제 provider 호출은 외부 데이터 전송 정책과 비용 검토 후 활성화해야 합니다.
LLM hypothesis는 검증된 사실이 아니며 JSON schema는 사실 정확성을 보장하지 않습니다.

Discord URL은 환경변수만 사용합니다. alert title/evidence/actions만 길이 제한을 적용해 보냅니다.
dedup key=(cluster,namespace,pod,container,category); severity 변화/재발 escalation과 persistent cooldown은 후속 작업입니다.

## API and modes

로컬은 loopback bind, 운영은 token/TLS/network control을 설정하세요.
모든 analyze request는 allowlist를 통과합니다. 단일 진행 중 분석 외 요청은 429입니다.
Ingress-level rate/body limits가 추가로 필요합니다. memory store는 1000건이며 영구 audit store가 아닙니다.

Alertmanager endpoint는 토큰이 없으면 disabled입니다. firing namespace만 사용하고 새 snapshot을 분석합니다.
실제 Alertmanager 설정은 수정하지 않았습니다. 외부 scheduler는 `scheduled_analysis`를 명시적으로 호출하며
iterations는 1–1000, interval_seconds는 최소 30초입니다. 기본은 1회/60초이며 import나 API 시작 시 자동 실행하지 않습니다.
운영 무한 루프는 실행하지 않았습니다.
