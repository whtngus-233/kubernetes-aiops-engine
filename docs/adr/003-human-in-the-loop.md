# ADR 003: Human in the loop

Status: Accepted

## Context

CrashLoop/OOM/5xx는 서로 다른 원인이 같은 상태로 나타나므로 잘못된 자동 복구가 장애를 확대할 수 있다.

## Decision

권한 없는 분석과 운영자의 확인/변경 결정을 분리한다. LLM에 shell/Kubernetes/AWS 도구를 주지 않고 automatic_action_taken=false를 유지한다.

## Consequences

평균 조사 시간 단축을 목표로 하며 복구 시간 개선 수치는 측정 없이 주장하지 않는다. 추후 자동화는 승인 정책과 감사·rollback을 별도로 설계해야 한다.
