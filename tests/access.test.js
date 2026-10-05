const test = require('node:test');
const assert = require('node:assert/strict');
const { requestJson, remember, readRemembered } = require('../admin_panel/access.js');

test('successful JSON and unavailable service', async () => {
    const original = global.fetch;
    try {
        global.fetch = async () => ({ ok: true, status: 200, text: async () => '{"user":"test"}' });
        assert.deepEqual(await requestJson('/test'), { user: 'test' });
        global.fetch = async () => ({ ok: false, status: 503, text: async () => '<html>unavailable</html>' });
        await assert.rejects(requestJson('/test'), error => error.status === 503 && /servicio/.test(error.message));
    } finally { global.fetch = original; }
});

test('timeout aborts a stalled body, not only connection establishment', async () => {
    const original = global.fetch;
    try {
        global.fetch = async (_, { signal }) => ({
            ok: true, status: 200,
            text: () => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))))
        });
        await assert.rejects(requestJson('/test', {}, 10), error => /tardó demasiado/.test(error.message));
    } finally { global.fetch = original; }
});

test('remembered access contains only identity; opt out and malformed storage', () => {
    const values = new Map();
    const storage = { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v), removeItem: k => values.delete(k) };
    remember(storage, true, 'test', 'cres-llano-largo');
    assert.deepEqual(readRemembered(storage), { username: 'test', campus: 'cres-llano-largo' });
    assert.equal(values.size, 1);
    remember(storage, false);
    assert.equal(readRemembered(storage), null);
    storage.setItem('sasu_remembered_access', 'invalid');
    assert.equal(readRemembered(storage), null);
});
