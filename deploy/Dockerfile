# H50 Console em contêiner (sem dependências além do Python).
# Construir a partir da raiz do repositório:  docker build -f deploy/Dockerfile -t h50console .
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    H50_HOST=0.0.0.0 H50_PORT=8050 H50_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md ./
COPY h50console ./h50console
RUN pip install --no-cache-dir . \
 && useradd --system --uid 10001 --home-dir /data h50 \
 && mkdir -p /data && chown h50 /data

USER h50
VOLUME /data
EXPOSE 8050

# o painel exige senha fora de localhost: use H50_PASSWORD ou pegue o código de primeiro acesso em `docker logs`
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8050/api/auth/status', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "h50console"]
