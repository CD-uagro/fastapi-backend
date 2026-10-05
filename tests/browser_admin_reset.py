"""Formulario del panel contra respuestas simuladas; no modifica cuentas reales."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[1] / 'admin_panel'
user = dict(id='user:test@cres-llano-largo', username='test', nombre_completo='Persona de prueba',
            email='test@example.com', campus='cres-llano-largo', rol='medico', activo=True, departamento='Salud')
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    page = browser.new_page()
    errors, requests = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route_request(route):
        path = urlparse(route.request.url).path
        if path.endswith('/reset-password'):
            requests.append(route.request.post_data_json)
            route.fulfill(content_type='application/json', body=json.dumps({'message': 'Contraseña restablecida.'}))
        elif path == '/auth/users':
            route.fulfill(content_type='application/json', body=json.dumps([user]))
        else:
            name = path.rsplit('/', 1)[-1] or 'index.html'
            file = root / name
            if not file.is_file():
                route.fulfill(status=404)
            else:
                route.fulfill(content_type='application/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'text/html', body=file.read_text(encoding='utf-8'))
    page.route('**/*', route_request)
    page.goto('http://sasu.test/admin/')
    page.evaluate("authToken='test';document.getElementById('login-screen').style.display='none';document.getElementById('dashboard-screen').style.display='flex';document.getElementById('users-table-container').style.display='block';document.getElementById('users-loading').style.display='none';")
    page.evaluate('(user) => renderUsersTable([user])', user)
    page.get_by_role('button', name='Restablecer contraseña', exact=True).click()
    expect(page.locator('#reset-password-target')).to_contain_text('test@example.com')
    page.locator('#reset-password-new').fill('SafePassword42')
    page.locator('#reset-password-repeat').fill('Different42')
    page.locator('#reset-password-verified').check()
    page.locator('#reset-password-submit').click()
    expect(page.locator('#reset-password-error')).to_contain_text('no coinciden')
    assert not requests
    page.locator('#reset-password-repeat').fill('SafePassword42')
    page.on('dialog', lambda dialog: dialog.accept())
    page.locator('#reset-password-submit').click()
    expect(page.locator('#reset-password-dialog')).not_to_be_visible()
    assert requests == [{'password': 'SafePassword42', 'identity_verified': True}]
    expect(page.locator('#reset-password-new')).to_have_value('')
    assert not errors, errors
    browser.close()
print('Admin reset browser OK')
