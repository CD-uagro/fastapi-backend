(() => {
    window.addEventListener('hashchange', () => {
        if (location.hash.startsWith('#token=')) location.reload();
    });
    let token = new URLSearchParams(location.hash.slice(1)).get('token');
    // El fragmento no se envía al servidor y se retira del historial visible.
    if (location.hash) history.replaceState(null, '', location.pathname);
    const requestForm = document.getElementById('request-recovery');
    const confirmForm = document.getElementById('confirm-recovery');
    const form = token ? confirmForm : requestForm;
    form.hidden = false;
    const button = form.querySelector('button');
    const status = document.getElementById('recovery-status');
    const error = document.getElementById('recovery-error');
    let busy = false;
    let enabled = false;
    const showError = message => { error.textContent = message; error.classList.add('show'); };

    async function initialize() {
        try {
            const [availability, institutions] = await Promise.all([
                SASUAccess.requestJson('/auth/password-recovery/status'),
                SASUAccess.requestJson('institutions.json')
            ]);
            institutions.forEach(institution => {
                const option = document.createElement('option');
                option.value = institution.value; option.textContent = institution.label;
                document.getElementById('recovery-campus').appendChild(option);
            });
            enabled = availability.enabled === true;
            button.disabled = !enabled;
            status.textContent = enabled ? (token ? 'Elige tu contraseña nueva.' : 'Escribe los datos de tu cuenta.')
                : 'La recuperación por correo aún no está habilitada. Contacta al responsable de SASU.';
        } catch (failure) { showError(failure.message); status.textContent = 'Recarga la página para volver a comprobar el servicio.'; }
    }

    document.getElementById('recovery-show-password').addEventListener('change', e => {
        ['new-password', 'repeat-password'].forEach(id => {
            document.getElementById(id).type = e.target.checked ? 'text' : 'password';
        });
    });

    form.addEventListener('submit', async e => {
        e.preventDefault();
        if (busy || !enabled) return;
        error.classList.remove('show');
        if (token && document.getElementById('new-password').value !== document.getElementById('repeat-password').value) {
            showError('Las contraseñas no coinciden.'); return;
        }
        const payload = token ? { token, password: document.getElementById('new-password').value } : {
            username: document.getElementById('recovery-user').value.trim(),
            campus: document.getElementById('recovery-campus').value,
            email: document.getElementById('recovery-email').value.trim()
        };
        const endpoint = token ? 'confirm' : 'request';
        busy = true; button.disabled = true; form.setAttribute('aria-busy', 'true');
        status.textContent = 'Procesando tu solicitud…';
        try {
            const result = await SASUAccess.requestJson('/auth/password-recovery/' + endpoint, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
            });
            status.textContent = result.message;
            if (token) {
                token = null; form.reset(); form.hidden = true;
                try { localStorage.removeItem('auth_token'); localStorage.removeItem('user_data'); } catch { /* Sin persistencia. */ }
            }
        } catch (failure) {
            showError(failure.status === 422 ? 'Revisa los campos. Si el enlace está incompleto, solicita uno nuevo.' : failure.message);
            status.textContent = 'Puedes corregir los datos o volver a intentar.';
        }
        finally { busy = false; button.disabled = !enabled; form.setAttribute('aria-busy', 'false'); }
    });
    initialize();
})();
