# Dockerfile for the MCP Logic stdio server.
FROM python:3.12-slim

ARG UV_VERSION=0.11.21

# Pin the build frontend and avoid retaining package caches in the image.
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

# The server and its solver subprocesses do not require root privileges.
RUN groupadd --gid 10001 mcp-logic \
    && useradd --create-home --uid 10001 --gid mcp-logic mcp-logic

WORKDIR /app
COPY --chown=mcp-logic:mcp-logic . .

RUN uv sync --locked --no-dev \
    && mkdir -p /usr/local/prover9-mount \
    && chown mcp-logic:mcp-logic /usr/local/prover9-mount

ENV PATH="/app/.venv/bin:${PATH}"

USER mcp-logic

# A stdio server has no network health endpoint. Validate the Python package
# and the two externally mounted solver executables instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import mcp_logic" \
    && test -x /usr/local/prover9-mount/prover9 \
    && test -x /usr/local/prover9-mount/mace4 || exit 1

CMD ["mcp_logic", "--prover-path", "/usr/local/prover9-mount"]
