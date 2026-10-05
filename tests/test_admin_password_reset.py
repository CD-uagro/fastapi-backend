import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import httpx
from fastapi import FastAPI
from azure.cosmos.exceptions import CosmosHttpResponseError
from admin_password_reset import build_admin_reset_router
from auth_service import AuthService


class AdminResetTests(unittest.TestCase):
    def setUp(self):
        self.users, self.audit = Mock(), Mock()
        self.doc = dict(id='user:test@cres-llano-largo', type='user', username='test',
                        activo=True, rol='medico', campus='cres-llano-largo',
                        password_hash='old', password_recovery={'token': 'old'},
                        intentos_fallidos=5, bloqueado_hasta='old', _etag='etag')
        self.users.read_item.return_value = self.doc
        self.app = FastAPI()
        self.app.include_router(build_admin_reset_router(self.users, self.audit))

    def request(self, role='admin', **payload):
        headers = {} if role is None else {'Authorization': 'Bearer ' + AuthService.create_access_token(
            {'sub': 'admin', 'rol': role, 'campus': 'cres-llano-largo'})}
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test') as client:
                return await client.post('/auth/users/user:test@cres-llano-largo/reset-password',
                                         headers=headers, json=dict(password='SafePassword42', identity_verified=True, **payload))
        return asyncio.run(run())

    def test_only_admin_can_reset(self):
        self.assertEqual(self.request(role=None).status_code, 401)
        self.assertEqual(self.request(role='medico').status_code, 403)
        self.users.container.replace_item.assert_not_called()

    def test_reset_preserves_account_and_consumes_recovery(self):
        with patch.object(AuthService, 'hash_password', return_value='new-hash'):
            response = self.request()
        self.assertEqual(response.status_code, 200)
        saved = self.users.container.replace_item.call_args.args[1]
        self.assertEqual(saved['rol'], 'medico')
        self.assertEqual(saved['campus'], self.doc['campus'])
        self.assertEqual(saved['password_hash'], 'new-hash')
        self.assertEqual(saved['intentos_fallidos'], 0)
        self.assertIsNone(saved['bloqueado_hasta'])
        self.assertNotIn('password_recovery', saved)
        self.assertEqual(self.users.container.replace_item.call_args.kwargs['etag'], 'etag')
        self.assertNotIn('SafePassword42', str(self.audit.call_args))
        self.assertNotIn('new-hash', response.text)

    def test_inactive_and_conflict_do_not_report_success(self):
        self.doc['activo'] = False
        self.assertEqual(self.request().status_code, 400)
        self.doc['activo'] = True
        self.users.container.replace_item.side_effect = CosmosHttpResponseError(status_code=412, message='conflict')
        with patch.object(AuthService, 'hash_password', return_value='hash'):
            self.assertEqual(self.request().status_code, 409)
        self.audit.assert_not_called()

    def test_validation(self):
        route = self.app.routes[-1].endpoint
        from admin_password_reset import AdminPasswordReset
        from fastapi import HTTPException
        for password, verified in [('SafePassword42', False), ('weakweak', True), ('Aa1' + 'é' * 36, True)]:
            with self.assertRaises(HTTPException) as caught:
                route(self.doc['id'], AdminPasswordReset(password=password, identity_verified=verified), SimpleNamespace(username='admin'))
            self.assertEqual(caught.exception.status_code, 400)
        self.users.container.replace_item.assert_not_called()
