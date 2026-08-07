FROM python:3.11-slim

WORKDIR /app

COPY packages/domain /app/packages/domain
RUN pip install --no-cache-dir -e /app/packages/domain

COPY packages/observability /app/packages/observability
RUN pip install --no-cache-dir -e /app/packages/observability

COPY apps/orchestrator/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY apps/orchestrator/src /app/src

ENV PORT=8080
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]

