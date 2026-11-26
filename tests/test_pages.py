import re

import pytest

from app.core.config import BASE_DIR

PAGES = ["/", "/balcao", "/camera", "/dashboard", "/review"]


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_with_strict_csp(client, path):
    response = client.get(path)
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
    csp = response.headers["content-security-policy"]
    for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "frame-ancestors 'none'", "object-src 'none'"):
        assert directive in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert response.headers["cache-control"] == "no-store"
    assert 'data-api="/api/v1"' in response.text


@pytest.mark.parametrize(
    "path",
    [f"app/templates/{n}" for n in ("base.html", "index.html", "balcao.html", "camera.html", "dashboard.html", "review.html")]
    + ["site/landing.html"],
)
def test_templates_have_no_inline_script_style_or_handlers(path):
    html = (BASE_DIR / path).read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "script inline"
    assert not re.search(r"<style\b", html) and not re.search(r'\sstyle="', html)
    assert not re.search(r"\son[a-z]+=", html, re.I), "handler inline"


def test_dashboard_pages_embed_no_data_or_secrets(client):
    for path in ("/dashboard", "/review"):
        html = client.get(path).text
        assert "pc_" not in html and "X-API-Key" not in html.replace("api-key", "")


@pytest.mark.parametrize("asset", ["common.js", "dashboard.js", "review.js", "camera.js", "balcao.js"])
def test_static_scripts_are_served(client, asset):
    response = client.get(f"/static/js/{asset}")
    assert response.status_code == 200 and "javascript" in response.headers["content-type"]


def test_scripts_never_use_innerhtml_or_eval():
    scripts = [*(BASE_DIR / "app" / "static" / "js").glob("*.js"), *(BASE_DIR / "site").glob("*.js")]
    assert len(scripts) >= 6
    for path in scripts:
        code = path.read_text(encoding="utf-8")
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert forbidden not in code, f"{path.name} usa {forbidden}"


def test_navigation_marks_current_page_and_uses_server_links(client):
    html = client.get("/balcao").text
    assert '<a href="/balcao" aria-current="page">Balcão</a>' in html
    assert 'href="/dashboard"' in html and 'href="/docs"' in html
    assert 'data-pages="server"' in html and "demo-banner" not in html and "demo.js" not in html


@pytest.mark.parametrize("asset", ["style.css", "img/icone.svg", "fonts/PlusJakartaSans.woff2"])
def test_brand_assets_are_served_locally(client, asset):
    """A CSP só permite recursos do próprio servidor: fonte e logo não vêm de CDN."""
    assert client.get(f"/static/{asset}").status_code == 200
