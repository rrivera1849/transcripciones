# Web app + worker image (CPU only; the GPU work happens on Modal).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg sqlite3 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv
COPY pyproject.toml uv.lock ./
COPY app ./app
COPY transcribe ./transcribe
COPY scripts ./scripts
RUN uv sync --frozen --no-dev --no-editable
ENV PATH="/srv/.venv/bin:$PATH" DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
# --proxy-headers: trust X-Forwarded-Proto/For from cloudflared so cookies are marked Secure
# and the login rate limit keys on the real client address.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
