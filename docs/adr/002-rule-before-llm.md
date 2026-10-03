# ADR 002: Rule before LLM

Status: Accepted

## Context

LLM은 제공되지 않은 원인을 추론하거나 출력 오류/timeout을 낼 수 있다.

## Decision

먼저 deterministic rule/correlation으로 관찰 증거를 분류하고 LLM은 별도 advisory JSON만 보완한다.

## Consequences

API key/LLM 장애에도 기본 분석이 유지된다. 규칙과 prompt/evaluation은 지속 관리해야 한다.
