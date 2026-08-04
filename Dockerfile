# syntax=docker/dockerfile:1

# Build the official OpenAI tunnel-client from a pinned release and commit.
# Pinning both values prevents an unexpectedly moved tag from changing the image.
FROM golang:1.26-bookworm AS tunnel-builder

ARG TUNNEL_CLIENT_VERSION=v0.0.10
ARG TUNNEL_CLIENT_COMMIT=105e17a79a36e4e5c897fd698ed2b8dbf935b144

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${TUNNEL_CLIENT_VERSION}" \
      https://github.com/openai/tunnel-client.git /src/tunnel-client \
    && test "$(git -C /src/tunnel-client rev-parse HEAD)" = "${TUNNEL_CLIENT_COMMIT}"

WORKDIR /src/tunnel-client
RUN CGO_ENABLED=0 go build \
      -trimpath \
      -buildvcs=false \
      -ldflags="-s -w -X github.com/openai/tunnel-client/pkg/version.GitSHA=${TUNNEL_CLIENT_COMMIT}" \
      -o /out/tunnel-client \
      ./cmd/client


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTMCP_HOST=127.0.0.1 \
    FASTMCP_PORT=8000 \
    MCP_SERVER_URL=http://127.0.0.1:8000/mcp \
    HEALTH_LISTEN_ADDR=127.0.0.1:8080 \
    LOG_LEVEL=info \
    LOG_FORMAT=json

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY requirements-mcp.txt ./requirements-mcp.txt
RUN python -m pip install -r requirements-mcp.txt

COPY --from=tunnel-builder /out/tunnel-client /usr/local/bin/tunnel-client
COPY src ./src
COPY deploy/start-cloud.sh ./deploy/start-cloud.sh

RUN chmod 0755 /usr/local/bin/tunnel-client /app/deploy/start-cloud.sh \
    && chown -R appuser:appuser /app

USER appuser

# No public port is exposed. Railway runs this as a persistent private worker.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/deploy/start-cloud.sh"]
