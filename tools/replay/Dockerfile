# =====================================================================
# full-shelf-demo-replay — public deterministic replay for judging
# ---------------------------------------------------------------------
# One container, two surfaces, nothing else:
#   * the built React frontend (static), and
#   * the session-scoped replay API, same-origin.
#
# This image is NOT part of the authoritative product architecture. It
# contains no Google client library, reads no credential, and reaches no
# Google service. It cannot mutate anything, because it holds nothing
# authoritative to mutate.
#
# The browser Maps key is deliberately NOT built in: Vite inlines every
# VITE_* value into the public bundle, so a key here would be published
# to anyone who views source. Without one the map renders Full Shelf's
# truthful deterministic schematic, which is an asserted product path.
# =====================================================================

# ---- stage 1: build the frontend ------------------------------------
FROM node:20-slim AS web

WORKDIR /build
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

COPY apps/web/ ./
# same-origin: the replay API is served by this same container.
ENV VITE_DATA_SOURCE=deterministic_replay \
    VITE_REPLAY_API_BASE=same-origin \
    VITE_JUDGE_MODE=1
# The browser Maps key is supplied at BUILD time, because Vite inlines every
# VITE_* value into the public bundle. That is safe only because the key is
# restricted to the Maps JavaScript API and to this service's own referrers —
# a browser key is always visible in page source, so restriction, not secrecy,
# is what protects it. Empty by default: an unrestricted key must never be
# built in, and without one the map degrades to the truthful schematic.
ARG VITE_GOOGLE_MAPS_API_KEY=""
ENV VITE_GOOGLE_MAPS_API_KEY=$VITE_GOOGLE_MAPS_API_KEY
RUN npm run build


# ---- stage 2: runtime ------------------------------------------------
FROM python:3.11-slim

# The replay needs no third-party Python package: it is the standard
# library plus the committed fixtures. Nothing to install means nothing
# to audit and no supply-chain surface.
WORKDIR /app

COPY tools/replay/events.py       /app/events.py
COPY tools/replay/session.py      /app/session.py
COPY tools/replay/locations.py    /app/locations.py
COPY tools/replay/public_server.py /app/public_server.py
COPY tools/replay/fixtures/       /app/fixtures/

COPY --from=web /build/dist/ /app/static/

# Unprivileged. Nothing in the image is written at runtime.
RUN useradd --system --uid 10001 --no-create-home replay \
    && chown -R replay:replay /app
USER 10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FULL_SHELF_STATIC_ROOT=/app/static \
    FULL_SHELF_JUDGE_MODE=1

# Cloud Run supplies PORT and the server binds it. 8080 is only the local
# default; the platform's value always wins.
ENV PORT=8080
EXPOSE 8080

CMD ["python", "/app/public_server.py"]
