# PratoCusto AI - imagem da API (Python 3.12)
#
# Observações:
#  * Webcam e balança USB/serial são equipamentos do computador: no Windows, o Docker Desktop
#    NÃO repassa esses dispositivos com facilidade. Para uso com hardware no Windows, rode
#    nativamente (scripts\instalar.ps1). A imagem serve bem para demonstração (mock), servidor,
#    PostgreSQL e testes. Em Linux, veja os comentários "devices" em docker-compose.yml.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libglib: dependência de runtime do OpenCV
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Usuário sem privilégios
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

WORKDIR /app

# Dependências primeiro (melhor uso de cache). Inclui o driver do PostgreSQL (uso opcional).
COPY requirements.txt requirements-postgres.txt ./
RUN pip install -r requirements-postgres.txt

COPY alembic.ini pyproject.toml ./
COPY app ./app

RUN mkdir -p /app/data /app/logs && chown -R app:app /app/data /app/logs

USER app

# Dentro do contêiner a API precisa escutar em 0.0.0.0; quem limita o acesso é a publicação da
# porta (no docker-compose.yml: apenas 127.0.0.1).
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/app/data \
    LOG_DIR=/app/logs \
    SQLITE_PATH=/app/data/pratocusto.db

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "app"]
