"""Verificações estáticas dos arquivos de empacotamento (Docker, scripts do Windows, dependências).

O Docker e o PowerShell não estão disponíveis no ambiente de testes: estes testes garantem as
propriedades de segurança e consistência dos arquivos, não a execução deles.
"""

import re

import pytest
import yaml

from app.core.config import BASE_DIR, Settings

ROOT = BASE_DIR


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------- Dockerfile


def test_dockerfile_runs_as_non_root_without_secrets():
    docker = read("Dockerfile")
    assert docker.startswith("# PratoCusto AI") and "FROM python:3.12" in docker
    assert re.search(r"^USER app$", docker, re.M), "o contêiner precisa rodar sem privilégios"
    assert docker.index("USER app") < docker.index('CMD ["python", "-m", "app"]')
    assert "HEALTHCHECK" in docker and "/api/v1/health" in docker
    for forbidden in ("COPY .env", "COPY . ", "ADD ", "API_KEY", "PASSWORD="):
        assert forbidden not in docker, forbidden
    assert "requirements-postgres.txt" in docker and "COPY app ./app" in docker


def test_dockerfile_copies_every_file_it_needs():
    docker = read("Dockerfile")
    for needed in ("requirements.txt", "requirements-postgres.txt", "alembic.ini", "pyproject.toml"):
        assert (ROOT / needed).is_file() and needed in docker
    assert (ROOT / "app" / "database" / "migrations" / "env.py").is_file()


def test_dockerignore_keeps_secrets_and_data_out_of_the_image():
    ignored = {line.strip() for line in read(".dockerignore").splitlines() if line.strip() and not line.startswith("#")}
    for entry in (".env", "data/", "logs/", "backups/", "*.db", ".git/", ".venv/", "tests/"):
        assert entry in ignored, entry
    assert "!.env.example" in ignored


# ------------------------------------------------------------------------ compose


def test_compose_publishes_only_on_loopback_and_hardens_container():
    compose = yaml.safe_load(read("docker-compose.yml"))
    app = compose["services"]["app"]
    assert app["ports"] == ["127.0.0.1:8000:8000"]
    assert "no-new-privileges:true" in app["security_opt"] and app["cap_drop"] == ["ALL"]
    assert app["environment"]["HOST"] == "0.0.0.0"  # noqa: S104 - escuta dentro do contêiner; a porta é publicada só em 127.0.0.1
    assert app["env_file"] == [{"path": ".env", "required": False}]
    assert set(compose["volumes"]) == {"pratocusto-data", "pratocusto-logs"}
    assert "pratocusto-data:/app/data" in app["volumes"]
    text = read("docker-compose.yml")
    assert not re.search(r"(?i)(password|api_key|secret)\s*:\s*[^$\s#]", text), "segredo literal no compose"


def test_compose_postgres_overlay_requires_password_and_hides_database():
    overlay = yaml.safe_load(read("docker-compose.postgres.yml"))
    db = overlay["services"]["db"]
    assert "ports" not in db, "o banco não pode ser publicado"
    for service in (overlay["services"]["app"], db):
        assert "?" in service["environment"]["POSTGRES_PASSWORD"], "senha obrigatória, sem valor padrão"
    assert overlay["services"]["app"]["environment"]["DATABASE_MODE"] == "postgresql"
    assert overlay["services"]["app"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert "healthcheck" in db


# --------------------------------------------------------------- scripts do Windows


@pytest.mark.parametrize("name", ["scripts/instalar.ps1", "scripts/iniciar.ps1", "scripts/backup.ps1"])
def test_powershell_scripts_are_safe_and_ascii(name):
    script = read(name)
    script.encode("ascii")  # PowerShell 5.1 lê UTF-8 sem BOM como ANSI: sem acentos
    assert '$ErrorActionPreference = "Stop"' in script
    assert "Set-Location (Split-Path -Parent $PSScriptRoot)" in script
    assert ".venv\\Scripts\\python.exe" in script
    for forbidden in ("Invoke-Expression", "iex ", "DownloadString", "Set-ExecutionPolicy", "pc_", "Remove-Item"):
        assert forbidden not in script, forbidden


def test_installer_covers_all_steps_and_checks_exit_codes():
    script = read("scripts/instalar.ps1")
    for step in ("-m venv .venv", "-m pip install -r requirements.txt", ".env.example", "-m app.cli migrate", "-m app.cli seed"):
        assert step in script, step
    assert "Python 3\\.12" in script and "param(" in script and "[switch]$Demo" in script
    assert script.count("$LASTEXITCODE") >= 5
    assert "if (-not (Test-Path \".env\"))" in script  # nunca sobrescreve o .env existente


@pytest.mark.parametrize("name", ["iniciar.bat", "instalar.bat"])
def test_batch_launchers_call_powershell_script_with_scoped_bypass(name):
    batch = read(name)
    batch.encode("ascii")
    script = name.replace(".bat", ".ps1")
    assert f'-File "%~dp0scripts\\{script}"' in batch
    assert "-ExecutionPolicy Bypass" in batch and "-NoProfile" in batch  # só para este processo
    assert (ROOT / "scripts" / script).is_file()


def test_gitattributes_forces_crlf_for_windows_scripts():
    attributes = read(".gitattributes")
    assert "*.bat text eol=crlf" in attributes and "*.ps1 text eol=crlf" in attributes


# ------------------------------------------------------------------- dependências


def test_requirements_are_pinned_and_cover_mandatory_technologies():
    lines = [l.strip() for l in read("requirements.txt").splitlines() if l.strip() and not l.startswith("#")]
    assert all("==" in l for l in lines), [l for l in lines if "==" not in l]
    names = {re.split(r"[=\[]", l)[0].lower() for l in lines}
    mandatory = {
        "fastapi", "sqlalchemy", "pydantic", "alembic", "opencv-python-headless", "pyserial", "uvicorn",
        "jinja2", "pytest", "httpx", "pillow", "python-multipart", "tzdata",
    }
    assert mandatory <= names, mandatory - names


def test_optional_requirement_files_reference_the_base_file():
    assert "-r requirements.txt" in read("requirements-postgres.txt") and "psycopg" in read("requirements-postgres.txt")
    assert "-r requirements.txt" in read("requirements-dev.txt")


def test_project_targets_python_312_and_ignores_secrets():
    assert 'requires-python = ">=3.12"' in read("pyproject.toml")
    ignore = {l.strip() for l in read(".gitignore").splitlines()}
    assert {".env", "data/", "logs/", "backups/", "*.db"} <= ignore


def test_env_example_has_no_secret_values_and_every_documented_setting_exists():
    env_text = read(".env.example")
    for secret in ("RECOGNITION_API_KEY", "POSTGRES_PASSWORD", "DATABASE_URL"):
        match = re.search(rf"^#?\s*{secret}=(.*)$", env_text, re.M)
        assert match and match.group(1).strip() in ("", "postgresql+psycopg://usuario:senha@localhost:5432/pratocusto"), secret
    declared = {m.group(1).lower() for m in re.finditer(r"^#?\s*([A-Z][A-Z0-9_]+)=", env_text, re.M)}
    known = set(Settings.model_fields)
    unknown = declared - known - {"postgres_password"}  # POSTGRES_PASSWORD existe em Settings; defensivo
    assert not unknown, f"variáveis do .env.example sem campo em Settings: {sorted(unknown)}"
