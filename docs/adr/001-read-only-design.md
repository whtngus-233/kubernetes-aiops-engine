# ADR 001: Read-only collection

Status: Accepted

## Context

실제 운영 EKS를 분석 대상으로 사용하기 때문에 분석 도구의 오류가 운영 상태를 바꾸면 안 된다.

## Decision

pods/events GET/list와 기존 observability HTTP 조회만 제공한다. Secrets와 mutation APIs는 노출하지 않는다.

## Consequences

자동 복구 효과는 없지만 blast radius를 제한하고 RBAC로 경계를 강제할 수 있다.
