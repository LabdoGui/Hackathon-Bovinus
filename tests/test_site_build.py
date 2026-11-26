"""Site estático do GitHub Pages (scripts/build_site.py)."""

import importlib.util
import json
import re

import pytest

from app import __version__
from app.core.config import BASE_DIR

APP_PAGES = ["index", "balcao", "camera", "dashboard", "review"]


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_site", BASE_DIR / "scripts" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    (out / "outro.md").write_text("não gerado", encoding="utf-8")
    _load_builder().build(out)
    return out


def _demo_data(path):
    text = path.read_text(encoding="utf-8")
    return json.loads(text[text.index("=") + 1 : text.rindex(";")])


def test_build_writes_landing_and_demo_pages(site):
    for name in APP_PAGES:
        assert (site / "app" / f"{name}.html").is_file()
    for asset in ("style.css", "img/icone.svg", "fonts/PlusJakartaSans.woff2", "js/common.js", "js/demo.js", "js/demo-data.js"):
        assert (site / "app" / "static" / asset).is_file()
    assert (site / "index.html").is_file() and (site / ".nojekyll").is_file() and (site / "assets" / "landing.css").is_file()
    assert (site / "outro.md").read_text(encoding="utf-8") == "não gerado"  # só apaga o que ele mesmo gera


@pytest.mark.parametrize("page", ["index.html", *[f"app/{p}.html" for p in APP_PAGES]])
def test_static_pages_are_self_contained(site, page):
    html = (site / page).read_text(encoding="utf-8")
    # GitHub Pages publica em /<repositório>/: todo link interno precisa ser relativo.
    assert not re.search(r'(?:href|src)="/(?!/)', html)
    assert '<meta http-equiv="Content-Security-Policy"' in html and "script-src 'self'" in html
    assert "unsafe-inline" not in html and "unsafe-eval" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and not re.search(r'\sstyle="', html)
    for ref in re.findall(r'(?:href|src)="([^"#?]+)', html):
        if not ref.startswith(("http://", "https://", "media/")):
            assert (site / page).parent.joinpath(ref).exists(), f"{page}: {ref} não existe"


def test_demo_pages_load_simulated_api_and_warn_visitor(site):
    html = (site / "app" / "balcao.html").read_text(encoding="utf-8")
    assert 'data-pages="static"' in html and "demo-banner" in html and "simulados" in html
    assert html.index("js/common.js") < html.index("js/demo.js") < html.index("js/balcao.js")
    assert 'href="dashboard.html"' in html and 'aria-current="page">Balcão' in html


def test_demo_catalog_comes_from_seed_with_recipe_costs(site):
    data = _demo_data(site / "app" / "static" / "js" / "demo-data.js")
    assert data["version"] == __version__ and data["timezone"] == "America/Sao_Paulo"
    foods = {f["name"]: f for f in data["foods"]}
    assert all(name.endswith("(demo)") for name in foods)
    assert foods["Arroz branco (demo)"]["cost_per_kg"] > 0
    without_recipe = [f for f in data["foods"] if f["recipe_id"] is None]
    assert without_recipe and all(f["cost_per_kg"] is None for f in without_recipe)
    assert data["stats"]["routes"] > 40 and data["stats"]["tables"] >= 10


def test_build_is_deterministic(site, tmp_path):
    _load_builder().build(tmp_path)
    for rel in ("app/static/js/demo-data.js", "app/balcao.html", "index.html"):
        assert (tmp_path / rel).read_bytes() == (site / rel).read_bytes(), rel


def test_published_docs_are_up_to_date(site):
    """docs/ é o que o GitHub Pages publica: rode ``python scripts/build_site.py`` após mudar páginas."""
    published = BASE_DIR / "docs"
    generated = sorted(p.relative_to(site) for p in site.rglob("*") if p.is_file() and p.name != "outro.md")
    for rel in generated:
        target = published / rel
        assert target.is_file(), f"docs/{rel} ausente: rode python scripts/build_site.py"
        same = target.read_bytes().replace(b"\r\n", b"\n") == (site / rel).read_bytes().replace(b"\r\n", b"\n")
        assert same, f"docs/{rel} desatualizado: rode python scripts/build_site.py"
