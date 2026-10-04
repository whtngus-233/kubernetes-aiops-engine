FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/aiops

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 aiops \
    && useradd --uid 10001 --gid 10001 --no-create-home aiops

COPY --chown=10001:10001 app ./app
COPY aiops-healthcheck /usr/local/bin/aiops-healthcheck

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD ["/usr/local/bin/aiops-healthcheck"]

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
