"""Sanitize all external text before reports, LLM requests or notifications."""
import re

_PATTERNS = [
    (r'(?i)\b([\"\x27]?authorization[\"\x27]?\s*[:=]\s*[\"\x27]?)(?:bearer\s+|basic\s+)?[^\s,;]+', r'\1[REDACTED]'),
    (r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [REDACTED]'),
    (r'(?i)(["\x27]?(?:api[-_]?key|password|passwd|secret|token|access[-_]?key|client[-_]?secret|aws[-_]?secret[-_]?access[-_]?key)["\x27]?\s*[:=]\s*)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s,;}&]+)', r'\1[REDACTED]'),
    (r'(?i)((?:set-cookie|cookie)\s*[:=]\s*)[^\r\n]+', r'\1[REDACTED]'),
    (r'(?i)(https?://)[^\s/:]+:[^\s/@]+@', r'\1[REDACTED]@'),
    (r'(?i)(https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/)[^\s"\x27]+', r'\1[REDACTED]'),
    (r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b', '[REDACTED]'),
    (r'\bsk-[A-Za-z0-9_-]{12,}\b', '[REDACTED]'),
    (r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[REDACTED]'),
    (r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', '[REDACTED]'),
]

def sanitize(value, limit=2000):
    text = str(value)
    for pattern, replacement in _PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.DOTALL)
    text = ''.join(c if c.isprintable() or c == '\n' else ' ' for c in text)
    return text[:limit]

def sanitize_tree(value):
    if isinstance(value, str):
        return sanitize(value)
    if isinstance(value, dict):
        return {sanitize(k): sanitize_tree(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_tree(v) for v in value]
    return value
