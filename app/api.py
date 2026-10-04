"""Local-first API. Endpoints accept namespace only, never commands or URLs."""
from hmac import compare_digest
from uuid import UUID
import threading
from fastapi import FastAPI, Depends, Header, HTTPException
from starlette.responses import JSONResponse
import asyncio
from pydantic import BaseModel, ConfigDict, Field
from app.config import Settings
from app.engine import AnalysisEngine
from app.store import IncidentStore
from app.collectors.kubernetes import CollectionError
from app.security import sanitize_tree

class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    namespace: str = Field(pattern=r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$', max_length=63)

class Alert(BaseModel):
    model_config = ConfigDict(extra='ignore')
    status: str = Field(pattern='^(firing|resolved)$')
    labels: dict[str, str] = Field(max_length=30)

class AlertmanagerRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')
    alerts: list[Alert] = Field(max_length=20)


def create_app(settings=None, engine=None, store=None):
    settings = settings or Settings.from_env()
    engine = engine or AnalysisEngine(settings)
    store = store or IncidentStore()
    app = FastAPI(title='Reusable Kubernetes AIOps Incident Analysis Platform', version='1.0.0')
    lock = threading.Lock()

    @app.middleware('http')
    async def bounded_body(request, call_next):
        if request.method == 'POST':
            try:
                async with asyncio.timeout(5):
                    chunks, size = [], 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 65536:
                            return JSONResponse({'detail': 'Request body exceeds limit'}, status_code=413)
                        chunks.append(chunk)
                    request._body = b''.join(chunks)
            except TimeoutError:
                return JSONResponse({'detail': 'Request body timeout'}, status_code=408)
        return await call_next(request)


    def auth(authorization: str | None = Header(default=None)):
        if settings.api_token and not compare_digest((authorization or '').encode(), ('Bearer ' + settings.api_token).encode()):
            raise HTTPException(401, 'Authentication required')

    def run(namespace):
        if namespace not in settings.allowed_namespaces:
            raise HTTPException(403, 'Namespace not allowed')
        if not lock.acquire(blocking=False):
            raise HTTPException(429, 'Analysis already in progress')
        try:
            incidents, warnings = engine.analyze(namespace)
            store.add_all(incidents)
            return {'incidents': [i.to_dict() for i in incidents], 'warnings': sanitize_tree(warnings),
                    'automatic_action_taken': False}
        except CollectionError:
            raise HTTPException(503, 'Kubernetes evidence unavailable') from None
        except Exception:
            raise HTTPException(503, 'Analysis unavailable') from None
        finally:
            lock.release()

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'mode': 'read-only', 'store': 'memory'}

    @app.post('/api/analyze', dependencies=[Depends(auth)])
    def analyze(request: AnalyzeRequest):
        return run(request.namespace)

    @app.get('/api/incidents', dependencies=[Depends(auth)])
    def incidents(limit: int = 100):
        if not 1 <= limit <= 1000:
            raise HTTPException(422, 'Invalid limit')
        return {'incidents': store.list(limit)}

    @app.get('/api/incidents/{incident_id}', dependencies=[Depends(auth)])
    def incident(incident_id: UUID):
        result = store.get(str(incident_id))
        if result is None:
            raise HTTPException(404, 'Incident not found')
        return result

    @app.post('/api/webhooks/alertmanager')
    def alertmanager(request: AlertmanagerRequest, x_alertmanager_token: str | None = Header(default=None)):
        if not settings.webhook_token:
            raise HTTPException(503, 'Webhook disabled')
        if not compare_digest((x_alertmanager_token or '').encode(), settings.webhook_token.encode()):
            raise HTTPException(401, 'Authentication required')
        namespaces = {a.labels.get('namespace') for a in request.alerts if a.status == 'firing'}
        if any(n not in settings.allowed_namespaces for n in namespaces):
            raise HTTPException(403, 'Namespace not allowed')
        # Alert annotations are not treated as evidence or instructions.
        return {'analyses': [run(n) for n in sorted(namespaces)]}

    return app

app = create_app()
