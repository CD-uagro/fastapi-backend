"""Prueba del panel en Chrome instalado. Todas las respuestas son locales simuladas."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / "admin_panel"
USER = dict(nombre_completo="Administrador de prueba", rol="admin", campus="cres-llano-largo")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=os.environ.get("SASU_BROWSER_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        )
        context = browser.new_context()
        state = {"login": 200, "me": 401, "calls": 0}

        def route_request(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            if parsed.hostname != "sasu.test":
                route.abort()
            elif path == "/auth/login":
                state["calls"] += 1
                route.fulfill(status=state["login"], content_type="application/json", body=json.dumps(
                    {"access_token": "test-token", "user": USER} if state["login"] == 200 else {"detail": "error"}))
            elif path == "/auth/me":
                route.fulfill(status=state["me"], content_type="application/json", body=json.dumps(USER if state["me"] == 200 else {"detail": "expired"}))
            elif path == "/auth/users":
                route.fulfill(content_type="application/json", body="[]")
            else:
                name = path.rsplit("/", 1)[-1] or "index.html"
                if name not in {"index.html", "app.js", "access.js", "styles.css"}:
                    route.fulfill(status=404, body="missing")
                else:
                    mime = "text/css" if name.endswith(".css") else "application/javascript" if name.endswith(".js") else "text/html"
                    route.fulfill(content_type=mime, body=(ROOT / name).read_text(encoding="utf-8"))

        context.route("**/*", route_request)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://sasu.test/admin/")
        expect(page.locator("#dashboard-screen")).to_be_hidden()
        expect(page.locator("#login-screen")).to_be_visible()
        page.locator("#login-username").fill("test")
        page.locator("#login-password").fill("example")
        page.locator("#show-password").check()
        expect(page.locator("#login-password")).to_have_attribute("type", "text")
        page.evaluate("document.getElementById('login-campus').setInstitucion('cres-llano-largo')")
        page.locator("#remember-access").check()
        state["login"] = 503
        page.locator("#login-password").press("Enter")
        expect(page.locator("#login-error")).to_contain_text("servicio")
        expect(page.locator("#login-btn")).to_be_enabled()
        state["login"] = 200
        page.locator("#login-btn").click()
        expect(page.locator("#dashboard-screen")).to_be_visible()
        expect(page.locator("#login-screen")).to_be_hidden()
        assert page.evaluate("JSON.parse(localStorage.getItem('sasu_remembered_access'))") == {"username": "test", "campus": "cres-llano-largo"}
        assert state["calls"] == 2
        page.reload()
        expect(page.locator("#login-error")).to_contain_text("venció")
        expect(page.locator("#dashboard-screen")).to_be_hidden()
        expect(page.locator("#login-username")).to_have_value("test")
        expect(page.locator("#login-password")).to_have_value("")
        page.locator("#remember-access").uncheck()
        assert page.evaluate("localStorage.getItem('sasu_remembered_access')") is None
        page.clock.install()
        page.evaluate("""() => { window.fetch = (_, options) => new Promise((resolve, reject) => {
            options.signal.addEventListener('abort', () => reject(new Error('aborted')));
        }); }""")
        page.locator("#login-password").fill("example")
        page.locator("#login-btn").click()
        page.evaluate("document.getElementById('login-form').dispatchEvent(new Event('submit', {cancelable: true}))")
        page.clock.fast_forward(31000)
        expect(page.locator("#login-error")).to_contain_text("tardó demasiado")
        expect(page.locator("#login-btn")).to_be_enabled()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        expect(page.locator("#dashboard-screen")).to_be_hidden()
        assert not errors, errors
        print("Navegador: acceso, error 503, sesión vencida, recuerdo, contraseña visible, timeout y vista móvil correctos.")
        browser.close()


if __name__ == "__main__":
    run()
