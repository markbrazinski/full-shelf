# =====================================================================
# full-shelf-judge — authenticated judge gateway (amendment CR-001)
# ---------------------------------------------------------------------
# Non-authoritative by construction. It carries no ADK, no google-genai,
# and no Spanner client, so the CR-001 prohibitions on agent logic and
# direct authoritative mutation are structural rather than promised.
#
# The plan-ledger address is deliberately never supplied to this image.
# =====================================================================

FROM node:20-slim AS web
WORKDIR /build
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
ARG VITE_GOOGLE_MAPS_API_KEY=""
ENV VITE_DATA_SOURCE=live \
    VITE_JUDGE_MODE=1 \
    VITE_LIVE_JUDGE=1 \
    VITE_REPLAY_API_BASE=same-origin \
    VITE_GOOGLE_MAPS_API_KEY=$VITE_GOOGLE_MAPS_API_KEY
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY apps/judge/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY apps/judge/src/main.py /app/main.py
COPY --from=web /build/dist/ /app/static/

RUN useradd --system --uid 10002 --no-create-home judge \
    && chown -R judge:judge /app
USER 10002

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FULL_SHELF_STATIC_ROOT=/app/static \
    PORT=8080
EXPOSE 8080
CMD ["python", "/app/main.py"]
