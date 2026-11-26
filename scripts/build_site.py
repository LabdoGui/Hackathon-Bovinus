"""Gera o site estático do GitHub Pages em ``docs/``.

O GitHub Pages só hospeda arquivos estáticos: não roda Python, balança nem banco de
dados. Por isso o site tem duas partes:

* ``docs/index.html``: página de apresentação do projeto;
* ``docs/app/``: as MESMAS páginas do sistema (balcão, câmera, painel, revisão),
  renderizadas a partir de ``app/templates`` e ligadas a uma API simulada que roda
  no navegador (``site/demo.js``), com balança e reconhecimento simulados e o
  catálogo fictício de demonstração (fichas técnicas "(demo)" do seed).

Os demais arquivos de ``docs/`` (documentação em Markdown, ``docs/media``) não são
tocados. Uso::

    python scripts/build_site.py            # gera em docs/
    python scripts/build_site.py --out X    # gera em outra pasta (testes)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from jinja2 import Environment, FileSystemLoader  # noqa: E402
from markupsafe import Markup  # noqa: E402

from app import __version__  # noqa: E402
from app.api.inventory import collect_routes  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.enums import CameraMode, Environment as AppEnv, RecognitionMode, ScaleMode  # noqa: E402
from app.database.seed import seed_demo_data  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.base import Base  # noqa: E402

REPO_URL = "https://github.com/LabdoGui/Hackathon-Bovinus"
REPO_BRANCH = "claude/magical-fermat-438tis"
PAGES = ("index", "balcao", "camera", "dashboard", "review")
GENERATED = ("index.html", ".nojekyll", "app", "assets")  # o que este script controla dentro de docs/
DEMO_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "media-src 'self' blob:; connect-src 'self'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
ID_NAMESPACE = uuid.UUID("5b0f9d3e-7c55-4a8e-9a8b-0c4d2b9e6f10")


def _stable_id(kind: str, name: str) -> str:
    """IDs estáveis entre builds (o seed gera UUIDs aleatórios)."""
    return str(uuid.uuid5(ID_NAMESPACE, f"{kind}:{name}"))


def collect_demo_data() -> dict:
    """Roda o seed de demonstração num banco temporário e exporta o catálogo pela própria API."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            _env_file=None,
            app_env=AppEnv.TEST,
            data_dir=tmp_path / "data",
            log_dir=tmp_path / "logs",
            log_to_file=False,
            log_level="WARNING",
            sqlite_path=tmp_path / "data" / "site.db",
            db_auto_migrate=False,
            scale_mode=ScaleMode.MOCK,
            camera_mode=CameraMode.MOCK,
            recognition_mode=RecognitionMode.MOCK,
            capture_export_enabled=False,
            allowed_hosts=["testserver"],
            api_require_key=False,
            default_price_per_kg=Decimal("59.90"),
        )
        app = create_app(settings)
        app.state.db.prepare()
        app.state.db.create_all()
        try:
            with app.state.db.session() as session:
                seed_demo_data(session)
                session.commit()
            with TestClient(app) as client:
                foods = client.get("/api/v1/foods", params={"limit": 200}).json()["items"]
                costs = {}
                for food in foods:
                    if food["recipe_id"]:
                        costs[food["id"]] = client.get(f"/api/v1/recipes/{food['recipe_id']}/cost").json()["cost_per_kg"]
            route_count = len(collect_routes(app))
        finally:
            app.state.db.dispose()

    exported = []
    for food in sorted(foods, key=lambda f: f["name"]):
        recipe = food.get("recipe")
        exported.append(
            {
                "id": _stable_id("food", food["name"]),
                "name": food["name"],
                "recognition_class": food["recognition_class"],
                "category": food.get("category"),
                "description": food.get("description"),
                "recipe_id": _stable_id("recipe", recipe["name"]) if recipe else None,
                "recipe": (
                    {"id": _stable_id("recipe", recipe["name"]), "name": recipe["name"], "yield_weight_g": recipe["yield_weight_g"]}
                    if recipe
                    else None
                ),
                "is_demo": food.get("is_demo", True),
                "active": food["active"],
                "cost_per_kg": costs.get(food["id"]),
            }
        )
    tz = settings.app_timezone
    offset = datetime.now(ZoneInfo(tz)).utcoffset()
    payload = {
        "version": __version__,
        "timezone": tz,
        "utc_offset_minutes": int(offset.total_seconds() // 60) if offset is not None else 0,
        "price_per_kg": float(settings.default_price_per_kg),
        "foods": exported,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:10]
    payload["data_version"] = f"{__version__}-{digest}"
    payload["stats"] = {"routes": route_count, "tables": len(Base.metadata.tables)}
    return payload


def _context(data: dict) -> dict:
    value = lambda text: SimpleNamespace(value=text)  # noqa: E731 - imita os enums do Settings
    foods = {f["recognition_class"]: f for f in data["foods"]}
    meat, rice = foods.get("carne_de_panela"), foods.get("arroz_branco")
    ratio = None
    if meat and rice and meat["cost_per_kg"] and rice["cost_per_kg"]:
        ratio = round(meat["cost_per_kg"] / rice["cost_per_kg"])
    return {
        "app_name": "PratoCusto AI",
        "version": data["version"],
        "settings": SimpleNamespace(
            api_require_key=False,
            app_env=value("demonstração"),
            database_mode=value("navegador"),
            scale_mode=value("simulada"),
            camera_mode=value("simulada ou webcam"),
            recognition_mode=value("simulado"),
        ),
        "api_prefix": "/api/v1",
        "page_url": lambda name: f"{name}.html",
        "docs_url": f"{REPO_URL}/blob/{REPO_BRANCH}/docs/endpoints.md",
        "repo_url": REPO_URL,
        "repo_branch": REPO_BRANCH,
        "demo": True,
        "demo_csp": Markup(DEMO_CSP),  # noqa: S704 - constante sem aspas duplas, segura dentro do atributo
        "stats": data["stats"],
        "meat": meat,
        "rice": rice,
        "ratio": ratio,
        "price_per_kg": data["price_per_kg"],
    }


def build(out: Path) -> list[Path]:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in GENERATED:  # limpa só o que é gerado aqui
        target = out / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    data = collect_demo_data()
    context = _context(data)
    env = Environment(loader=FileSystemLoader([BASE_DIR / "app" / "templates", BASE_DIR / "site"]), autoescape=True)
    written: list[Path] = []

    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)

    # Demonstração: as páginas do sistema com a API simulada.
    shutil.copytree(BASE_DIR / "app" / "static", out / "app" / "static", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(BASE_DIR / "site" / "demo.js", out / "app" / "static" / "js" / "demo.js")
    write(
        out / "app" / "static" / "js" / "demo-data.js",
        "/* Gerado por scripts/build_site.py a partir do seed de demonstração (dados fictícios). */\n"
        "window.PC_DEMO_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n",
    )
    url_for = lambda _name, path: f"static/{path}"  # noqa: E731
    for name in PAGES:
        html = env.get_template(f"{name}.html").render(**context, active=name, url_for=url_for)
        write(out / "app" / f"{name}.html", html)

    # Página de apresentação.
    shutil.copytree(BASE_DIR / "site" / "assets", out / "assets")
    media = BASE_DIR / "docs" / "media"  # vídeo de apresentação (versionado à parte, não gerado aqui)
    landing = env.get_template("landing.html").render(
        **context,
        url_for=lambda _name, path: f"app/static/{path}",
        has_video=(media / "pratocusto.mp4").exists(),
        has_poster=(media / "pratocusto-poster.jpg").exists(),
    )
    write(out / "index.html", landing)
    write(out / ".nojekyll", "")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=BASE_DIR / "docs", help="pasta de saída (padrão: docs/)")
    args = parser.parse_args(argv)
    written = build(args.out)
    print(f"Site gerado em {args.out} ({len(written)} arquivos escritos, {datetime.now(UTC):%Y-%m-%d %H:%M} UTC).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
