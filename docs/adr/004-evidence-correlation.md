# ADR 004: Evidence correlation

Status: Accepted

## Context

Pod 상태만으로 root cause를 확인하기 어렵고 다른 workload/과거 로그를 섞으면 오진한다.

## Decision

source/timestamp/namespace/pod/container 공통 모델과 freshness window로 status/event/metric/log를 연결한다. Event는 Pod UID로 연결한다.

## Consequences

설명 가능한 confidence와 traceable evidence를 얻지만 metric/log UID 부족과 instant metrics의 추이 한계는 남는다.
