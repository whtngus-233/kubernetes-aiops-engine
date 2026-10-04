"""Scan source allowlist only; never inspect credentials, .env or kubeconfig."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b', r'\bsk-[A-Za-z0-9_-]{20,}\b',
            r'https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{30,}',
            r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
            r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b',
            r'(?i)(?:api_key|password|webhook_url|access_token)\s*[:=]\s*["\x27][A-Za-z0-9+/=_-]{24,}["\x27]']
paths = [ROOT / name for name in ('README.md','Dockerfile','.gitignore','.dockerignore','config.example.yaml','.env.example','requirements.txt','requirements-dev.txt')]
for name in ('app','tests','examples','docs','charts','scripts'):
    paths.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.md','.yaml','.json','.tpl','.sh','.c'))
findings=[]
for path in paths:
    if not path.exists(): continue
    for number,line in enumerate(path.read_text().splitlines(),1):
        if any(re.search(pattern,line) for pattern in PATTERNS):
            findings.append(f'{path.relative_to(ROOT)}:{number}: potential secret (value suppressed)')
print('\n'.join(findings) if findings else f'Secret pattern scan passed ({len(paths)} source files); heuristic only.')
sys.exit(bool(findings))
