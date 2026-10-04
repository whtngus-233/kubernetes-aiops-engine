"""Run using: python -m app.main"""
import argparse
import sys
import json
from app.config import Settings, NAMESPACE
from app.engine import AnalysisEngine
from pathlib import Path
import yaml
from app.analyzers.rules import RuleEngine
from app.collectors.kubernetes import CollectionError, KubernetesCollector
from app.report import render_report, render_structured


def main(argv=None):
    parser = argparse.ArgumentParser(description="READ-ONLY Kubernetes incident analysis")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--namespace")
    parser.add_argument("--context", help="기본: 현재 kubeconfig context")
    parser.add_argument("--restart-threshold", type=int)
    parser.add_argument('--structured', action='store_true', help='Enable evidence correlation pipeline')
    parser.add_argument('--format', choices=('terminal', 'json'), default='terminal')
    parser.add_argument('--output', type=Path, help='Explicit report output; refuses to overwrite existing files')
    args = parser.parse_args(argv)
    collector = None
    try:
        settings = yaml.safe_load(args.config.read_text()) if args.config else {}
        if settings is None:
            settings = {}
        if not isinstance(settings, dict) or set(settings) - {"namespace", "context", "restart_threshold"}:
            raise ValueError("설정은 namespace/context/restart_threshold만 포함하는 mapping이어야 합니다.")
        namespace = args.namespace if args.namespace is not None else settings.get("namespace", "default")
        context = args.context if args.context is not None else settings.get("context")
        threshold = args.restart_threshold if args.restart_threshold is not None else settings.get("restart_threshold", 5)
        if not isinstance(namespace, str) or not NAMESPACE.fullmatch(namespace):
            raise ValueError("namespace는 비어 있지 않은 문자열이어야 합니다.")
        if context is not None and (not isinstance(context, str) or not context.strip()):
            raise ValueError("context는 비어 있지 않은 문자열이어야 합니다.")
        configuration = Settings.from_env()
        if namespace not in configuration.allowed_namespaces:
            raise ValueError('Namespace not allowed')
        engine = RuleEngine(threshold)
        collector = KubernetesCollector(context=context)
        snapshot = collector.collect(namespace)
        warnings = snapshot.warnings
        if args.structured or args.format == 'json':
            from dataclasses import replace
            configuration = replace(configuration, context=context,
                                    restart_threshold=threshold)
            reports, warnings = AnalysisEngine(configuration).analyze_snapshot(snapshot)
            report = (json.dumps({'incidents': [i.to_dict() for i in reports], 'warnings': warnings,
                                  'automatic_action_taken': False}, ensure_ascii=False, indent=2)
                      if args.format == 'json' else render_structured(reports, warnings))
        else:
            report = render_report(snapshot, engine.analyze(snapshot))
        if args.output:
            with args.output.open('x') as output:
                output.write(report + '\n')
        print(report)
        return 2 if warnings else 0
    except CollectionError as error:
        print(f"분석 실패: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, yaml.YAMLError):
        print("분석 실패: kubeconfig/인증/연결 또는 설정 파일과 옵션을 확인하세요. "
              "설정 키: namespace, context, restart_threshold(1 이상 정수).", file=sys.stderr)
        return 1
    finally:
        if collector:
            collector.close()


if __name__ == "__main__":
    raise SystemExit(main())
