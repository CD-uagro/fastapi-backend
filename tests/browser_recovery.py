"""Prueba de recuperación en navegador: sin correos ni cuentas reales."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / "admin_panel"


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get(
            "SASU_BROWSER_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
        context = browser.new_context()
        state = {"enabled": False, "confirm": 400, "calls": []}

        def route_request(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            if parsed.hostname != "sasu.test":
                route.abort()
            elif path == "/auth/password-recovery/status":
                route.fulfill(content_type="application/json", body=json.dumps({"enabled": state["enabled"]}))
            elif path in ("/auth/password-recovery/request", "/auth/password-recovery/confirm"):
                state["calls"].append((path, route.request.post_data_json))
                status = 202 if path.endswith("request") else state["confirm"]
                body = {"message": "Si los datos coinciden, recibirás un enlace."} if status == 202 else (
                    {"message": "Contraseña actualizada."} if status == 200 else {"detail": "El enlace venció. Solicita uno nuevo."})
                route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
            else:
                name = path.rsplit("/", 1)[-1]
                if name not in {"recover.html", "recovery.js", "access.js", "styles.css", "institutions.json"}:
                    route.fulfill(status=404, body="missing")
                else:
                    mime = "text/css" if name.endswith(".css") else "application/javascript" if name.endswith(".js") else "application/json" if name.endswith(".json") else "text/html"
                    route.fulfill(content_type=mime, body=(ROOT / name).read_text(encoding="utf-8"))

        context.route("**/*", route_request)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("https://sasu.test/admin/recover.html")
        expect(page.locator("#recovery-status")).to_contain_text("aún no está habilitada")
        expect(page.locator("#request-recovery button")).to_be_disabled()
        state["enabled"] = True
        page.reload()
        expect(page.locator("#request-recovery button")).to_be_enabled()
        page.locator("#recovery-user").fill("medico")
        page.locator("#recovery-campus").select_option("cres-llano-largo")
        page.locator("#recovery-email").fill("medico@example.com")
        page.locator("#request-recovery button").click()
        expect(page.locator("#recovery-status")).to_contain_text("recibirás un enlace")
        assert state["calls"][-1][1]["username"] == "medico"
        token = "opaque-test-token"
        page.goto("https://sasu.test/admin/recover.html#token=" + token)
        expect(page.locator("#confirm-recovery")).to_be_visible()
        expect(page.locator("#request-recovery")).to_be_hidden()
        expect(page.locator("#confirm-recovery button")).to_be_enabled()
        assert "token" not in page.url
        page.locator("#new-password").fill("NewPassword123!")
        page.locator("#repeat-password").fill("Different123!")
        page.locator("#confirm-recovery button").click()
        expect(page.locator("#recovery-error")).to_contain_text("no coinciden")
        assert len(state["calls"]) == 1
        page.locator("#repeat-password").fill("NewPassword123!")
        page.locator("#recovery-show-password").check()
        expect(page.locator("#new-password")).to_have_attribute("type", "text")
        page.locator("#confirm-recovery button").click()
        expect(page.locator("#recovery-error")).to_contain_text("venció")
        expect(page.locator("#confirm-recovery button")).to_be_enabled()
        state["confirm"] = 200
        page.evaluate("localStorage.setItem('auth_token','previous-token')")
        page.locator("#confirm-recovery button").click()
        expect(page.locator("#recovery-status")).to_contain_text("Contraseña actualizada")
        expect(page.locator("#confirm-recovery")).to_be_hidden()
        assert page.evaluate("localStorage.getItem('auth_token')") is None
        assert state["calls"][-1][1]["token"] == token
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        print("Recuperación web: deshabilitada, solicitud, enlace oculto del historial, repetición, enlace vencido, confirmación y móvil correctos.")
        browser.close()


if __name__ == "__main__":
    run()
