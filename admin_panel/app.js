// ============================================
// SASU Admin Panel - JavaScript
// ============================================

// Configuración
const API_BASE_URL = window.location.origin;
const accessStorage = (() => { try { return window.localStorage; } catch { return null; } })();
let accessBusy = false;
let authToken = null;
let currentUser = null;

// ============================================
// GESTIÓN DE AUTENTICACIÓN
// ============================================

// Verificar si hay sesión activa al cargar
document.addEventListener('DOMContentLoaded', async () => {
    crearAutocompletado('login-campus');
    crearAutocompletado('form-campus');
    const remembered = SASUAccess.readRemembered(accessStorage);
    if (remembered) {
        document.getElementById('login-username').value = remembered.username;
        document.getElementById('login-campus').setInstitucion(remembered.campus);
        document.getElementById('remember-access').checked = true;
    }
    document.getElementById('remember-access').addEventListener('change', e => {
        if (!e.target.checked) SASUAccess.remember(accessStorage, false);
    });
    document.getElementById('show-password').addEventListener('change', e => {
        document.getElementById('login-password').type = e.target.checked ? 'text' : 'password';
    });
    showLogin();
    try { authToken = accessStorage.getItem('auth_token'); } catch { authToken = null; }
    if (!authToken) return;
    setAccessBusy(true, 'Comprobando tu sesi\u00f3n...');
    try {
        currentUser = await SASUAccess.requestJson(`${API_BASE_URL}/auth/me`, {
            headers: { Authorization: `Bearer ${authToken}` }
        });
        if (currentUser.rol !== 'admin') throw new SASUAccess.ApiError('Solo administradores pueden acceder al panel.', 403);
        showDashboard();
    } catch (error) {
        clearSession();
        showLogin();
        showError('login-error', error.status === 401
            ? 'Tu sesi\u00f3n venci\u00f3. Inicia sesi\u00f3n de nuevo.' : error.message);
    } finally { setAccessBusy(false); }
});

function clearSession() {
    authToken = null;
    currentUser = null;
    try {
        accessStorage.removeItem('auth_token');
        accessStorage.removeItem('user_data');
    } catch { /* Sin almacenamiento persistente. */ }
}

function setAccessBusy(busy, message = '') {
    accessBusy = busy;
    const btn = document.getElementById('login-btn');
    btn.disabled = busy;
    btn.querySelector('.spinner').style.display = busy ? 'block' : 'none';
    btn.querySelector('span').style.display = busy ? 'none' : 'block';
    document.getElementById('login-status').textContent = message;
    document.getElementById('login-form').setAttribute('aria-busy', String(busy));
}

function showLogin() {
    document.getElementById('login-screen').classList.add('active');
    document.getElementById('dashboard-screen').classList.remove('active');
}

function showDashboard() {
    document.getElementById('login-screen').classList.remove('active');
    document.getElementById('dashboard-screen').classList.add('active');
    
    // Actualizar UI con info del usuario
    updateUserInfo();
    
    // Cargar vista inicial (usuarios)
    showView('users');
}

function updateUserInfo() {
    if (!currentUser) return;
    
    document.getElementById('user-name').textContent = currentUser.nombre_completo;
    document.getElementById('user-role').textContent = getRoleLabel(currentUser.rol);
    document.getElementById('user-campus').textContent = getCampusLabel(currentUser.campus);
    
    // Iniciales para avatar
    const initials = currentUser.nombre_completo
        .split(' ')
        .map(n => n[0])
        .join('')
        .substring(0, 2)
        .toUpperCase();
    document.getElementById('user-initials').textContent = initials;
}

// ============================================
// LOGIN
// ============================================

document.getElementById('login-form').addEventListener('submit', async e => {
    e.preventDefault();
    if (accessBusy) return;
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const campusInput = document.getElementById('login-campus');
    const campus = campusInput.getSelectedValue ? campusInput.getSelectedValue() : null;
    if (!username || !password) {
        showError('login-error', 'Complete usuario y contrase\u00f1a');
        return;
    }
    if (!campus) {
        showError('login-error', 'Selecciona una instituci\u00f3n de las opciones sugeridas');
        return;
    }
    setAccessBusy(true, 'Conectando con SASU...');
    hideError('login-error');
    const slowNotice = setTimeout(() => {
        document.getElementById('login-status').textContent = 'El servidor est\u00e1 tardando. Seguimos esperando su respuesta...';
    }, 5000);
    try {
        const data = await SASUAccess.requestJson(`${API_BASE_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, campus })
        });
        if (!data.user || !data.access_token) throw new Error('Respuesta de acceso incompleta. Intenta de nuevo.');
        if (data.user.rol !== 'admin') throw new Error('Solo administradores pueden acceder al panel');
        authToken = data.access_token;
        currentUser = data.user;
        try {
            accessStorage.setItem('auth_token', authToken);
            accessStorage.setItem('user_data', JSON.stringify(currentUser));
        } catch { /* La sesi\u00f3n actual puede continuar sin persistencia. */ }
        SASUAccess.remember(accessStorage, document.getElementById('remember-access').checked, username, campus);
        document.getElementById('login-password').value = '';
        showDashboard();
    } catch (error) {
        showError('login-error', error.message);
    } finally {
        clearTimeout(slowNotice);
        setAccessBusy(false);
    }
});

// ============================================
// LOGOUT
// ============================================

document.getElementById('logout-btn').addEventListener('click', () => {
    if (confirm('¿Está seguro que desea cerrar sesión?')) {
        clearSession();
        showLogin();
    }
});

// ============================================
// NAVEGACIÓN ENTRE VISTAS
// ============================================

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        const view = item.dataset.view;
        showView(view);
        
        // Actualizar navegación activa
        document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
    });
});

function showView(viewName) {
    // Ocultar todas las vistas
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    
    // Mostrar la vista seleccionada
    document.getElementById(`${viewName}-view`).classList.add('active');
    
    // Cargar datos según la vista
    if (viewName === 'users') {
        loadUsers();
    } else if (viewName === 'audit') {
        loadAuditLogs();
    } else if (viewName === 'settings') {
        loadSettings();
    }
}

// ============================================
// GESTIÓN DE USUARIOS
// ============================================

async function loadUsers() {
    const loading = document.getElementById('users-loading');
    const tableContainer = document.getElementById('users-table-container');
    const empty = document.getElementById('users-empty');
    
    loading.style.display = 'block';
    tableContainer.style.display = 'none';
    empty.style.display = 'none';
    
    try {
        const campus = document.getElementById('filter-campus').value;
        const rol = document.getElementById('filter-role').value;
        
        let url = `${API_BASE_URL}/auth/users?`;
        if (campus) url += `campus=${campus}&`;
        if (rol) url += `rol=${rol}&`;
        
        const users = await SASUAccess.requestJson(url, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (users.length === 0) {
            empty.style.display = 'block';
        } else {
            renderUsersTable(users);
            tableContainer.style.display = 'block';
        }
        
    } catch (error) {
        alert('Error al cargar usuarios: ' + error.message);
    } finally {
        loading.style.display = 'none';
    }
}

function renderUsersTable(users) {
    const tbody = document.getElementById('users-tbody');
    tbody.innerHTML = '';
    
    users.forEach(user => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${user.username}</strong></td>
            <td>${user.nombre_completo}</td>
            <td><span class="badge badge-primary">${getRoleLabel(user.rol)}</span></td>
            <td>${getCampusLabel(user.campus)}</td>
            <td>${user.departamento}</td>
            <td>
                <span class="badge ${user.activo ? 'badge-success' : 'badge-danger'}">
                    ${user.activo ? '✓ Activo' : '✗ Inactivo'}
                </span>
            </td>
            <td>${formatDate(user.ultimo_acceso)}</td>
            <td>
                <button class="btn-icon" onclick="editUser('${user.id}')" title="Editar">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </button>
                <button class="btn-icon" onclick="toggleUserStatus('${user.id}', ${user.activo})" title="${user.activo ? 'Desactivar' : 'Activar'}">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        ${user.activo ? 
                            '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>' :
                            '<polyline points="20 6 9 17 4 12"></polyline>'
                        }
                    </svg>
                </button>
            </td>
        `;
        const resetButton = document.createElement('button');
        resetButton.type = 'button';
        resetButton.className = 'btn btn-secondary';
        resetButton.textContent = 'Restablecer contraseña';
        resetButton.disabled = !user.activo;
        resetButton.addEventListener('click', () => openPasswordReset(user));
        tr.lastElementChild.appendChild(resetButton);
        tbody.appendChild(tr);
    });
    
    // Aplicar búsqueda en tiempo real
    applyUserSearch();
}

// Filtros y búsqueda
document.getElementById('user-search').addEventListener('input', applyUserSearch);
document.getElementById('filter-campus').addEventListener('change', loadUsers);
document.getElementById('filter-role').addEventListener('change', loadUsers);
document.getElementById('refresh-users-btn').addEventListener('click', loadUsers);

function applyUserSearch() {
    const searchTerm = document.getElementById('user-search').value.toLowerCase();
    const rows = document.querySelectorAll('#users-tbody tr');
    
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(searchTerm) ? '' : 'none';
    });
}

// ============================================
// CREAR/EDITAR USUARIO
// ============================================

document.getElementById('new-user-btn').addEventListener('click', () => {
    openUserModal();
});

function openUserModal(userId = null) {
    const modal = document.getElementById('user-modal');
    const form = document.getElementById('user-form');
    const title = document.getElementById('modal-title');
    const passwordSection = document.getElementById('password-section');
    
    // Limpiar formulario y estado
    form.reset();
    delete form.dataset.editingUserId;
    document.getElementById('form-username').disabled = false;
    hideError('form-error');
    
    if (userId) {
        title.textContent = 'Editar Usuario';
        passwordSection.style.display = 'none';
        document.getElementById('form-password').removeAttribute('required');
        // La función editUser() llenará los datos
    } else {
        title.textContent = 'Nuevo Usuario';
        passwordSection.style.display = 'block';
        document.getElementById('form-password').setAttribute('required', 'required');
    }
    
    modal.classList.add('active');
}

function closeUserModal() {
    document.getElementById('user-modal').classList.remove('active');
}

// Cerrar modal al hacer clic fuera
document.getElementById('user-modal').addEventListener('click', (e) => {
    if (e.target.id === 'user-modal') {
        closeUserModal();
    }
});

document.getElementById('user-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const form = e.target;
    const isEditing = form.dataset.editingUserId;
    
    const campusInput = document.getElementById('form-campus');
    const campusValue = campusInput.getSelectedValue ? campusInput.getSelectedValue() : null;
    
    if (!campusValue) {
        showError('form-error', 'Por favor selecciona una institución de las opciones sugeridas');
        return;
    }
    
    const formData = {
        email: document.getElementById('form-email').value.trim(),
        nombre_completo: document.getElementById('form-nombre').value.trim(),
        rol: document.getElementById('form-rol').value,
        campus: campusValue,
        departamento: document.getElementById('form-departamento').value.trim()
    };
    
    // Si no estamos editando, agregar username y password
    if (!isEditing) {
        formData.username = document.getElementById('form-username').value.trim();
        formData.password = document.getElementById('form-password').value;
    }
    
    // Validaciones
    if ((!isEditing && !formData.username) || !formData.email || !formData.nombre_completo || 
        !formData.rol || !formData.departamento) {
        showError('form-error', 'Todos los campos son obligatorios');
        return;
    }
    
    if (!isEditing && formData.password && formData.password.length < 8) {
        showError('form-error', 'La contraseña debe tener al menos 8 caracteres');
        return;
    }
    
    const btn = e.target.querySelector('button[type="submit"]');
    const spinner = btn.querySelector('.spinner');
    const span = btn.querySelector('span');
    
    btn.disabled = true;
    spinner.style.display = 'block';
    span.style.display = 'none';
    hideError('form-error');
    
    try {
        let response;
        
        if (isEditing) {
            // Editar usuario existente
            response = await fetch(`${API_BASE_URL}/auth/users/${isEditing}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                },
                body: JSON.stringify(formData)
            });
        } else {
            // Crear nuevo usuario
            response = await fetch(`${API_BASE_URL}/auth/register`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                },
                body: JSON.stringify(formData)
            });
        }
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Error al ${isEditing ? 'actualizar' : 'crear'} usuario`);
        }
        
        // Limpiar estado de edición
        delete form.dataset.editingUserId;
        document.getElementById('form-username').disabled = false;
        
        // Cerrar modal y recargar usuarios
        closeUserModal();
        loadUsers();
        
        // Mensaje de éxito
        alert(`✓ Usuario ${isEditing ? 'actualizado' : 'creado'} exitosamente`);
        
    } catch (error) {
        showError('form-error', error.message);
    } finally {
        btn.disabled = false;
        spinner.style.display = 'none';
        span.style.display = 'block';
    }
});

async function toggleUserStatus(userId, currentStatus) {
    const action = currentStatus ? 'desactivar' : 'activar';
    if (!confirm(`¿Está seguro que desea ${action} este usuario?`)) return;
    
    try {
        const response = await fetch(`${API_BASE_URL}/auth/users/${userId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ activo: !currentStatus })
        });
        
        if (!response.ok) throw new Error('Error al actualizar usuario');
        
        loadUsers();
        alert(`✓ Usuario ${action} correctamente`);
        
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

async function editUser(userId) {
    try {
        // Cargar datos del usuario
        const response = await fetch(`${API_BASE_URL}/auth/users`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (!response.ok) throw new Error('Error al cargar usuario');
        
        const users = await response.json();
        const user = users.find(u => u.id === userId);
        
        if (!user) {
            alert('Usuario no encontrado');
            return;
        }
        
        // Abrir modal y pre-llenar formulario
        const modal = document.getElementById('user-modal');
        const form = document.getElementById('user-form');
        const title = document.getElementById('modal-title');
        const passwordSection = document.getElementById('password-section');
        
        title.textContent = 'Editar Usuario';
        passwordSection.style.display = 'none';
        document.getElementById('form-password').removeAttribute('required');
        
        // Llenar campos
        document.getElementById('form-username').value = user.username;
        document.getElementById('form-username').disabled = true; // No se puede cambiar username
        document.getElementById('form-email').value = user.email;
        document.getElementById('form-nombre').value = user.nombre_completo;
        document.getElementById('form-rol').value = user.rol;
        
        // Establecer institución con autocompletado
        const campusInput = document.getElementById('form-campus');
        if (campusInput.setInstitucion) {
            campusInput.setInstitucion(user.campus);
        } else {
            campusInput.value = user.campus;
        }
        
        document.getElementById('form-departamento').value = user.departamento;
        
        // Guardar userId en el formulario para saber que estamos editando
        form.dataset.editingUserId = userId;
        
        modal.classList.add('active');
        
    } catch (error) {
        alert('Error al cargar usuario: ' + error.message);
    }
}

// ============================================
// AUDITORÍA
// ============================================

async function loadAuditLogs() {
    const loading = document.getElementById('audit-loading');
    const tableContainer = document.getElementById('audit-table-container');
    
    loading.style.display = 'block';
    tableContainer.style.display = 'none';
    
    try {
        const usuario = document.getElementById('audit-search').value.trim();
        const accion = document.getElementById('filter-action').value;
        
        let url = `${API_BASE_URL}/auth/audit-logs?limit=100`;
        if (usuario) url += `&usuario=${usuario}`;
        if (accion) url += `&accion=${accion}`;
        
        const response = await fetch(url, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (!response.ok) throw new Error('Error al cargar logs');
        
        const logs = await response.json();
        renderAuditTable(logs);
        tableContainer.style.display = 'block';
        
    } catch (error) {
        alert('Error al cargar auditoría: ' + error.message);
    } finally {
        loading.style.display = 'none';
    }
}

function renderAuditTable(logs) {
    const tbody = document.getElementById('audit-tbody');
    tbody.innerHTML = '';
    
    logs.forEach(log => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${formatDateTime(log.timestamp)}</td>
            <td><strong>${log.usuario}</strong></td>
            <td><span class="badge badge-info">${log.accion}</span></td>
            <td>${log.recurso || '-'}</td>
            <td>${log.detalles || '-'}</td>
            <td>${log.ip || '-'}</td>
        `;
        tbody.appendChild(tr);
    });
}

document.getElementById('audit-search').addEventListener('input', () => {
    clearTimeout(window.auditSearchTimeout);
    window.auditSearchTimeout = setTimeout(loadAuditLogs, 500);
});

document.getElementById('filter-action').addEventListener('change', loadAuditLogs);
document.getElementById('refresh-audit-btn').addEventListener('click', loadAuditLogs);

document.getElementById('export-audit-btn').addEventListener('click', () => {
    const table = document.getElementById('audit-table');
    const rows = Array.from(table.querySelectorAll('tr'));
    
    const csv = rows.map(row => {
        const cells = Array.from(row.querySelectorAll('th, td'));
        return cells.map(cell => `"${cell.textContent.trim()}"`).join(',');
    }).join('\n');
    
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `auditoria-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
});

// ============================================
// CONFIGURACIÓN
// ============================================

async function loadSettings() {
    document.getElementById('api-url').textContent = API_BASE_URL;
    
    try {
        // Cargar estadísticas
        const usersResponse = await fetch(`${API_BASE_URL}/auth/users`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        const users = await usersResponse.json();
        document.getElementById('total-users').textContent = users.length;
        
        const auditResponse = await fetch(`${API_BASE_URL}/auth/audit-logs?limit=1000`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        const audit = await auditResponse.json();
        document.getElementById('total-audit').textContent = audit.length;
        
    } catch (error) {
        console.error('Error al cargar estadísticas:', error);
    }
}

document.getElementById('clear-cache-btn').addEventListener('click', () => {
    if (confirm('¿Está seguro que desea limpiar el caché local?')) {
        localStorage.clear();
        alert('Caché limpiado. Por favor inicie sesión nuevamente.');
        showLogin();
    }
});

// ============================================
// UTILIDADES
// ============================================

function showError(elementId, message) {
    const errorDiv = document.getElementById(elementId);
    errorDiv.textContent = message;
    errorDiv.classList.add('show');
    errorDiv.style.display = 'block';
}

function hideError(elementId) {
    const errorDiv = document.getElementById(elementId);
    errorDiv.classList.remove('show');
    errorDiv.style.display = 'none';
}

function getRoleLabel(rol) {
    const labels = {
        'admin': 'Administrador',
        'medico': 'Médico',
        'nutricion': 'Nutrición',
        'psicologia': 'Psicología',
        'odontologia': 'Odontología',
        'enfermeria': 'Enfermería',
        'recepcion': 'Recepción',
        'servicios_estudiantiles': 'Servicios Estudiantiles',
        'lectura': 'Solo Lectura'
    };
    return labels[rol] || rol;
}

function getCampusLabel(campus) {
    // Buscar en la lista de instituciones
    const institucion = INSTITUCIONES.find(i => i.value === campus);
    return institucion ? institucion.label : campus;
}

function formatDate(dateString) {
    if (!dateString) return 'Nunca';
    const date = new Date(dateString);
    return date.toLocaleDateString('es-MX', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatDateTime(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleString('es-MX', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

// ============================================
// AUTOCOMPLETADO DE INSTITUCIONES
// ============================================

// Lista completa de instituciones UAGro (88 total)
const INSTITUCIONES = [
    // CRES - Campus Regionales (6)
    { value: 'cres-cruz-grande', label: 'CRES Campus Cruz Grande (Costa Chica)', categoria: 'CRES' },
    { value: 'cres-zumpango', label: 'CRES Campus Zumpango (Zona Centro)', categoria: 'CRES' },
    { value: 'cres-taxco-viejo', label: 'CRES Campus Taxco el Viejo (Zona Norte)', categoria: 'CRES' },
    { value: 'cres-huamuxtitlan', label: 'CRES Campus Huamuxtitlán (Montaña)', categoria: 'CRES' },
    { value: 'cres-llano-largo', label: 'CRES Campus Llano Largo (Acapulco)', categoria: 'CRES' },
    { value: 'cres-tecpan', label: 'CRES Campus Tecpán (Costa Grande)', categoria: 'CRES' },
    
    // Clínicas Universitarias (4)
    { value: 'clinica-chilpancingo', label: 'Clínica Universitaria UAGro – Chilpancingo', categoria: 'Clínica' },
    { value: 'clinica-acapulco', label: 'Clínica Universitaria UAGro – Acapulco', categoria: 'Clínica' },
    { value: 'clinica-iguala', label: 'Clínica Universitaria UAGro – Iguala', categoria: 'Clínica' },
    { value: 'clinica-ometepec', label: 'Servicio Médico Universitario – Ometepec', categoria: 'Clínica' },
    
    // Facultades - Centro (8)
    { value: 'fac-gobierno', label: 'Facultad de Gobierno y Gestión Pública', categoria: 'Facultad' },
    { value: 'fac-arquitectura', label: 'Facultad de Arquitectura y Urbanismo', categoria: 'Facultad' },
    { value: 'fac-quimico', label: 'Facultad de Ciencias Químico Biológicas', categoria: 'Facultad' },
    { value: 'fac-comunicacion', label: 'Facultad de Comunicación y Mercadotecnia', categoria: 'Facultad' },
    { value: 'fac-derecho-chil', label: 'Facultad de Derecho (Chilpancingo)', categoria: 'Facultad' },
    { value: 'fac-filosofia', label: 'Facultad de Filosofía y Letras', categoria: 'Facultad' },
    { value: 'fac-ingenieria', label: 'Facultad de Ingeniería', categoria: 'Facultad' },
    { value: 'fac-matematicas-centro', label: 'Facultad de Matemáticas (Centro)', categoria: 'Facultad' },
    
    // Facultades - Sur/Acapulco (10)
    { value: 'fac-contaduria', label: 'Facultad de Contaduría y Administración', categoria: 'Facultad' },
    { value: 'fac-derecho-aca', label: 'Facultad de Derecho (Acapulco)', categoria: 'Facultad' },
    { value: 'fac-ecologia', label: 'Facultad de Ecología Marina', categoria: 'Facultad' },
    { value: 'fac-economia', label: 'Facultad de Economía (Campus Llano Largo)', categoria: 'Facultad' },
    { value: 'fac-enfermeria2', label: 'Facultad de Enfermería No. 2', categoria: 'Facultad' },
    { value: 'fac-matematicas-sur', label: 'Facultad de Matemáticas (Sur)', categoria: 'Facultad' },
    { value: 'fac-lenguas', label: 'Facultad de Lenguas Extranjeras', categoria: 'Facultad' },
    { value: 'fac-medicina', label: 'Facultad de Medicina', categoria: 'Facultad' },
    { value: 'fac-odontologia', label: 'Facultad de Odontología', categoria: 'Facultad' },
    { value: 'fac-turismo', label: 'Facultad de Turismo', categoria: 'Facultad' },
    
    // Facultades - Norte (2)
    { value: 'fac-agropecuarias', label: 'Facultad de Ciencias Agropecuarias y Ambientales', categoria: 'Facultad' },
    { value: 'fac-matematicas-norte', label: 'Facultad de Matemáticas (Norte)', categoria: 'Facultad' },
    
    // Preparatorias (50)
    { value: 'prep-1', label: 'Escuela Preparatoria No. 1', categoria: 'Preparatoria' },
    { value: 'prep-2', label: 'Escuela Preparatoria No. 2', categoria: 'Preparatoria' },
    { value: 'prep-3', label: 'Escuela Preparatoria No. 3', categoria: 'Preparatoria' },
    { value: 'prep-4', label: 'Escuela Preparatoria No. 4', categoria: 'Preparatoria' },
    { value: 'prep-5', label: 'Escuela Preparatoria No. 5', categoria: 'Preparatoria' },
    { value: 'prep-6', label: 'Escuela Preparatoria No. 6', categoria: 'Preparatoria' },
    { value: 'prep-7', label: 'Escuela Preparatoria No. 7', categoria: 'Preparatoria' },
    { value: 'prep-8', label: 'Escuela Preparatoria No. 8', categoria: 'Preparatoria' },
    { value: 'prep-9', label: 'Escuela Preparatoria No. 9', categoria: 'Preparatoria' },
    { value: 'prep-10', label: 'Escuela Preparatoria No. 10', categoria: 'Preparatoria' },
    { value: 'prep-11', label: 'Escuela Preparatoria No. 11', categoria: 'Preparatoria' },
    { value: 'prep-12', label: 'Escuela Preparatoria No. 12', categoria: 'Preparatoria' },
    { value: 'prep-13', label: 'Escuela Preparatoria No. 13', categoria: 'Preparatoria' },
    { value: 'prep-14', label: 'Escuela Preparatoria No. 14', categoria: 'Preparatoria' },
    { value: 'prep-15', label: 'Escuela Preparatoria No. 15', categoria: 'Preparatoria' },
    { value: 'prep-16', label: 'Escuela Preparatoria No. 16', categoria: 'Preparatoria' },
    { value: 'prep-17', label: 'Escuela Preparatoria No. 17', categoria: 'Preparatoria' },
    { value: 'prep-18', label: 'Escuela Preparatoria No. 18', categoria: 'Preparatoria' },
    { value: 'prep-19', label: 'Escuela Preparatoria No. 19', categoria: 'Preparatoria' },
    { value: 'prep-20', label: 'Escuela Preparatoria No. 20', categoria: 'Preparatoria' },
    { value: 'prep-21', label: 'Escuela Preparatoria No. 21', categoria: 'Preparatoria' },
    { value: 'prep-22', label: 'Escuela Preparatoria No. 22', categoria: 'Preparatoria' },
    { value: 'prep-23', label: 'Escuela Preparatoria No. 23', categoria: 'Preparatoria' },
    { value: 'prep-24', label: 'Escuela Preparatoria No. 24', categoria: 'Preparatoria' },
    { value: 'prep-25', label: 'Escuela Preparatoria No. 25', categoria: 'Preparatoria' },
    { value: 'prep-26', label: 'Escuela Preparatoria No. 26', categoria: 'Preparatoria' },
    { value: 'prep-27', label: 'Escuela Preparatoria No. 27', categoria: 'Preparatoria' },
    { value: 'prep-28', label: 'Escuela Preparatoria No. 28', categoria: 'Preparatoria' },
    { value: 'prep-29', label: 'Escuela Preparatoria No. 29', categoria: 'Preparatoria' },
    { value: 'prep-30', label: 'Escuela Preparatoria No. 30', categoria: 'Preparatoria' },
    { value: 'prep-31', label: 'Escuela Preparatoria No. 31', categoria: 'Preparatoria' },
    { value: 'prep-32', label: 'Escuela Preparatoria No. 32', categoria: 'Preparatoria' },
    { value: 'prep-33', label: 'Escuela Preparatoria No. 33', categoria: 'Preparatoria' },
    { value: 'prep-34', label: 'Escuela Preparatoria No. 34', categoria: 'Preparatoria' },
    { value: 'prep-35', label: 'Escuela Preparatoria No. 35', categoria: 'Preparatoria' },
    { value: 'prep-36', label: 'Escuela Preparatoria No. 36', categoria: 'Preparatoria' },
    { value: 'prep-37', label: 'Escuela Preparatoria No. 37', categoria: 'Preparatoria' },
    { value: 'prep-38', label: 'Escuela Preparatoria No. 38', categoria: 'Preparatoria' },
    { value: 'prep-39', label: 'Escuela Preparatoria No. 39', categoria: 'Preparatoria' },
    { value: 'prep-40', label: 'Escuela Preparatoria No. 40', categoria: 'Preparatoria' },
    { value: 'prep-41', label: 'Escuela Preparatoria No. 41', categoria: 'Preparatoria' },
    { value: 'prep-42', label: 'Escuela Preparatoria No. 42', categoria: 'Preparatoria' },
    { value: 'prep-43', label: 'Escuela Preparatoria No. 43', categoria: 'Preparatoria' },
    { value: 'prep-44', label: 'Escuela Preparatoria No. 44', categoria: 'Preparatoria' },
    { value: 'prep-45', label: 'Escuela Preparatoria No. 45', categoria: 'Preparatoria' },
    { value: 'prep-46', label: 'Escuela Preparatoria No. 46', categoria: 'Preparatoria' },
    { value: 'prep-47', label: 'Escuela Preparatoria No. 47', categoria: 'Preparatoria' },
    { value: 'prep-48', label: 'Escuela Preparatoria No. 48', categoria: 'Preparatoria' },
    { value: 'prep-49', label: 'Escuela Preparatoria No. 49', categoria: 'Preparatoria' },
    { value: 'prep-50', label: 'Escuela Preparatoria No. 50', categoria: 'Preparatoria' },
    
    // Rectoría y Coordinaciones Regionales (8)
    { value: 'rectoria', label: 'Rectoría / Administración Central', categoria: 'Rectoría' },
    { value: 'coord-sur', label: 'Coordinación Regional Zona Sur (Acapulco)', categoria: 'Coordinación' },
    { value: 'coord-centro', label: 'Coordinación Regional Zona Centro', categoria: 'Coordinación' },
    { value: 'coord-norte', label: 'Coordinación Regional Zona Norte', categoria: 'Coordinación' },
    { value: 'coord-costa-chica', label: 'Coordinación Regional Costa Chica', categoria: 'Coordinación' },
    { value: 'coord-costa-grande', label: 'Coordinación Regional Costa Grande', categoria: 'Coordinación' },
    { value: 'coord-montana', label: 'Coordinación Regional Montaña', categoria: 'Coordinación' },
    { value: 'coord-tierra-caliente', label: 'Coordinación Regional Tierra Caliente', categoria: 'Coordinación' }
];

/**
 * Búsqueda fuzzy/flexible de instituciones
 * Encuentra las mejores coincidencias basadas en el texto ingresado
 */
function buscarInstituciones(query, maxResults = 5) {
    if (!query || query.trim() === '') {
        return INSTITUCIONES.slice(0, maxResults);
    }
    
    const queryLower = query.toLowerCase().trim();
    const palabrasQuery = queryLower.split(/\s+/);
    
    // Calcular score de relevancia para cada institución
    const resultados = INSTITUCIONES.map(inst => {
        let score = 0;
        const labelLower = inst.label.toLowerCase();
        const categoriaLower = inst.categoria.toLowerCase();
        
        // Coincidencia exacta al inicio (máxima prioridad)
        if (labelLower.startsWith(queryLower)) {
            score += 100;
        }
        
        // Contiene la búsqueda completa
        if (labelLower.includes(queryLower)) {
            score += 50;
        }
        
        // Coincidencia en categoría
        if (categoriaLower.includes(queryLower)) {
            score += 30;
        }
        
        // Coincidencia de palabras individuales
        palabrasQuery.forEach(palabra => {
            if (labelLower.includes(palabra)) {
                score += 20;
            }
            // Coincidencia aproximada (primeras letras)
            const palabrasLabel = labelLower.split(/\s+/);
            palabrasLabel.forEach(palabraLabel => {
                if (palabraLabel.startsWith(palabra)) {
                    score += 10;
                }
            });
        });
        
        // Coincidencia de números (para preparatorias)
        const numeros = query.match(/\d+/g);
        if (numeros) {
            numeros.forEach(num => {
                if (inst.value.includes(num)) {
                    score += 40;
                }
            });
        }
        
        return { ...inst, score };
    });
    
    // Filtrar solo resultados con score > 0 y ordenar por relevancia
    return resultados
        .filter(r => r.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, maxResults);
}

/**
 * Crear componente de autocompletado para un input
 */
function crearAutocompletado(inputId, onSelect) {
    const input = document.getElementById(inputId);
    if (!input) return;
    
    // Crear contenedor de sugerencias
    const sugerenciasDiv = document.createElement('div');
    sugerenciasDiv.className = 'autocomplete-suggestions';
    sugerenciasDiv.id = `${inputId}-suggestions`;
    input.parentNode.style.position = 'relative';
    input.parentNode.appendChild(sugerenciasDiv);
    
    // Variable para almacenar el valor seleccionado
    let valorSeleccionado = null;
    
    // Evento de escritura en el input
    input.addEventListener('input', function() {
        const query = this.value;
        valorSeleccionado = null; // Reset al escribir
        
        if (query.length === 0) {
            sugerenciasDiv.innerHTML = '';
            sugerenciasDiv.style.display = 'none';
            return;
        }
        
        const resultados = buscarInstituciones(query, 5);
        
        if (resultados.length === 0) {
            sugerenciasDiv.innerHTML = '<div class="autocomplete-item no-results">No se encontraron coincidencias</div>';
            sugerenciasDiv.style.display = 'block';
            return;
        }
        
        // Generar HTML de sugerencias
        sugerenciasDiv.innerHTML = resultados.map(inst => `
            <div class="autocomplete-item" data-value="${inst.value}">
                <span class="inst-label">${inst.label}</span>
                <span class="inst-categoria">${inst.categoria}</span>
            </div>
        `).join('');
        
        sugerenciasDiv.style.display = 'block';
        
        // Eventos click en sugerencias
        sugerenciasDiv.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', function() {
                const value = this.getAttribute('data-value');
                const inst = INSTITUCIONES.find(i => i.value === value);
                
                if (inst) {
                    input.value = inst.label;
                    valorSeleccionado = inst.value;
                    sugerenciasDiv.style.display = 'none';
                    
                    if (onSelect) {
                        onSelect(inst.value, inst.label);
                    }
                }
            });
        });
    });
    
    // Cerrar sugerencias al hacer clic fuera
    document.addEventListener('click', function(e) {
        if (!input.contains(e.target) && !sugerenciasDiv.contains(e.target)) {
            sugerenciasDiv.style.display = 'none';
        }
    });
    
    // Función para obtener el valor seleccionado
    input.getSelectedValue = function() {
        return valorSeleccionado;
    };
    
    // Función para establecer valor programáticamente
    input.setInstitucion = function(value) {
        const inst = INSTITUCIONES.find(i => i.value === value);
        if (inst) {
            input.value = inst.label;
            valorSeleccionado = inst.value;
        }
    };
}

console.log('✅ SASU Admin Panel cargado correctamente');
console.log('🔐 API:', API_BASE_URL);

// Restablecimiento asistido: nunca conservar contraseñas en almacenamiento del navegador.
let resetUserId = null;
let resetBusy = false;
function openPasswordReset(user) {
    if (resetBusy) return;
    document.getElementById('reset-password-form').reset();
    document.getElementById('reset-password-new').type = 'password';
    document.getElementById('reset-password-repeat').type = 'password';
    document.getElementById('reset-password-error').textContent = '';
    document.getElementById('reset-password-target').textContent =
        `${user.nombre_completo} - ${user.username} - ${getCampusLabel(user.campus)} - ${user.email}`;
    resetUserId = user.id;
    document.getElementById('reset-password-dialog').showModal();
}
document.getElementById('reset-password-cancel').addEventListener('click', () => {
    if (!resetBusy) document.getElementById('reset-password-dialog').close();
});
document.getElementById('reset-password-dialog').addEventListener('cancel', event => {
    if (resetBusy) event.preventDefault();
});
document.getElementById('reset-password-dialog').addEventListener('close', () => {
    document.getElementById('reset-password-form').reset();
    resetUserId = null;
});
document.getElementById('reset-password-show').addEventListener('change', event => {
    for (const id of ['reset-password-new', 'reset-password-repeat']) {
        document.getElementById(id).type = event.target.checked ? 'text' : 'password';
    }
});
document.getElementById('reset-password-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (resetBusy || !resetUserId) return;
    const errorBox = document.getElementById('reset-password-error');
    const password = document.getElementById('reset-password-new').value;
    errorBox.textContent = '';
    if (password !== document.getElementById('reset-password-repeat').value) {
        errorBox.textContent = 'Las contraseñas no coinciden.';
        return;
    }
    if (!/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/[0-9]/.test(password) || password.length < 8 || new TextEncoder().encode(password).length > 72) {
        errorBox.textContent = 'Usa al menos 8 caracteres, mayúsculas, minúsculas y números; máximo 72 bytes.';
        return;
    }
    resetBusy = true;
    const button = document.getElementById('reset-password-submit');
    button.disabled = true;
    button.textContent = 'Guardando...';
    try {
        const result = await SASUAccess.requestJson(`${API_BASE_URL}/auth/users/${encodeURIComponent(resetUserId)}/reset-password`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${authToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ password, identity_verified: document.getElementById('reset-password-verified').checked })
        });
        document.getElementById('reset-password-dialog').close();
        alert(result.message);
        loadUsers();
    } catch (error) {
        errorBox.textContent = error.status === 409 ? 'La cuenta cambió. Actualiza la lista y vuelve a intentar.' : error.message;
    } finally {
        resetBusy = false;
        button.disabled = false;
        button.textContent = 'Restablecer contraseña';
    }
});
