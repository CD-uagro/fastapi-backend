// Solicitudes acotadas: el límite incluye la lectura del cuerpo de respuesta.
const SASUAccess = (() => {
    class ApiError extends Error {
        constructor(message, status) { super(message); this.status = status; }
    }

    async function requestJson(url, options = {}, timeoutMs = 30000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetch(url, { ...options, signal: controller.signal });
            const body = await response.text();
            let data;
            try { data = body ? JSON.parse(body) : null; }
            catch { data = null; }
            if (!response.ok) {
                let message;
                if (response.status === 401) message = 'Usuario, contraseña o institución incorrectos, o sesión vencida.';
                else if (response.status === 403) message = typeof data?.detail === 'string' ? data.detail : 'Acceso denegado.';
                else if (response.status === 422) message = 'Revisa el usuario y selecciona una institución de la lista.';
                else if (response.status === 429) message = 'Hay demasiadas solicitudes. Espera un momento y reintenta.';
                else if (response.status === 400) message = typeof data?.detail === 'string' ? data.detail : 'Revisa los datos e intenta de nuevo.';
                else message = 'El servicio no está disponible en este momento. Intenta de nuevo.';
                throw new ApiError(message, response.status);
            }
            if (!data) throw new ApiError('El servidor envió una respuesta inesperada. Intenta de nuevo.', response.status);
            return data;
        } catch (error) {
            if (error instanceof ApiError) throw error;
            if (controller.signal.aborted) throw new ApiError('El servidor tardó demasiado. Puedes volver a intentar.', 0);
            throw new ApiError('No se pudo conectar. Revisa tu conexión y vuelve a intentar.', 0);
        } finally { clearTimeout(timer); }
    }

    function readRemembered(storage) {
        try {
            const value = JSON.parse(storage.getItem('sasu_remembered_access'));
            return value && typeof value.username === 'string' && typeof value.campus === 'string'
                ? { username: value.username, campus: value.campus } : null;
        } catch { return null; }
    }

    function remember(storage, enabled, username, campus) {
        try {
            if (enabled) storage.setItem('sasu_remembered_access', JSON.stringify({ username, campus }));
            else storage.removeItem('sasu_remembered_access');
        } catch { /* El acceso funciona aunque el navegador impida recordar datos. */ }
    }
    return { requestJson, readRemembered, remember, ApiError };
})();
if (typeof module !== 'undefined') module.exports = SASUAccess;
