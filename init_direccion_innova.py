"""
Script para crear el primer usuario admin: DireccionInnovaSalud
Usa el endpoint especial /auth/init-admin que no requiere autenticación previa
"""
import os
import requests
import json

# Configuración
API_BASE_URL = os.environ.get(
    "INIT_ADMIN_API_BASE_URL",
    "https://fastapi-backend-o7ks.onrender.com",
)
# Para desarrollo local: API_BASE_URL = "http://localhost:8000"
ADMIN_PASSWORD = os.environ.get("INIT_ADMIN_PASSWORD")

if not ADMIN_PASSWORD:
    raise SystemExit(
        "Define INIT_ADMIN_PASSWORD antes de ejecutar este script."
    )

# Datos del usuario admin
admin_data = {
    "username": "DireccionInnovaSalud",
    "email": "innovasalud@uagro.mx",
    "nombre_completo": "Direccion Innova Salud",  # Sin acento
    "rol": "admin",
    "campus": "cres-llano-largo",  # FIX: Formato correcto
    "departamento": "Direccion",  # Sin acento
    "password": ADMIN_PASSWORD
}

print("=" * 70)
print("🏥 CREAR PRIMER ADMIN: DireccionInnovaSalud")
print("=" * 70)
print()
print(f"📡 Backend: {API_BASE_URL}")
print()

# Verificar que el backend esté disponible
print("🔍 Verificando conexión con el backend...")
try:
    health_response = requests.get(f"{API_BASE_URL}/health", timeout=15)
    if health_response.status_code == 200:
        print("✅ Backend disponible")
    else:
        print("⚠️  Backend respondió con error")
except requests.exceptions.Timeout:
    print("⏱️  Backend tardando (cold start), esperando 30 segundos...")
    import time
    time.sleep(30)
except Exception as e:
    print(f"❌ Error de conexión: {e}")
    print("\n⚠️  Asegúrate que el backend esté desplegado en Render.com")
    exit(1)

# Crear admin
print()
print("🔄 Creando usuario administrador...")
print()

try:
    response = requests.post(
        f"{API_BASE_URL}/auth/init-admin",
        json=admin_data,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    
    if response.status_code == 200:
        user = response.json()
        print("=" * 70)
        print("✅ USUARIO ADMINISTRADOR CREADO EXITOSAMENTE")
        print("=" * 70)
        print()
        print(f"ID:              {user['id']}")
        print(f"Usuario:         {user['username']}")
        print(f"Email:           {user['email']}")
        print(f"Nombre:          {user['nombre_completo']}")
        print(f"Rol:             {user['rol']}")
        print(f"Campus:          {user['campus']}")
        print(f"Departamento:    {user['departamento']}")
        print(f"Estado:          {'✓ Activo' if user['activo'] else '✗ Inactivo'}")
        print(f"Fecha creación:  {user['fecha_creacion']}")
        print()
        print("=" * 70)
        print("🔐 CREDENCIALES DE ACCESO AL PANEL WEB")
        print("=" * 70)
        print()
        print(f"🌐 URL del panel:  {API_BASE_URL}/admin")
        print()
        print(f"   Usuario:        {admin_data['username']}")
        print("   Contraseña:     definida en INIT_ADMIN_PASSWORD")
        print(f"   Campus:         {admin_data['campus']}")
        print()
        print("=" * 70)
        print()
        print("🎯 PRÓXIMOS PASOS:")
        print()
        print("1. Acceder al panel web: {}/admin".format(API_BASE_URL))
        print("2. Iniciar sesión con las credenciales de arriba")
        print("3. Crear usuarios adicionales desde el panel")
        print("4. (IMPORTANTE) Cambiar la contraseña del admin")
        print()
        print("⚠️  NOTA: El endpoint /auth/init-admin se desactivó automáticamente")
        print("   No se pueden crear más admins por este método.")
        print()
        
    elif response.status_code == 403:
        error = response.json()
        print("=" * 70)
        print("⚠️  EL SISTEMA YA TIENE UN ADMINISTRADOR")
        print("=" * 70)
        print()
        print(f"Detalle: {error.get('detail', 'Ya existe un admin')}")
        print()
        print("Para crear más usuarios:")
        print("1. Inicia sesión como admin en: {}/admin".format(API_BASE_URL))
        print("2. Usa el botón 'Nuevo Usuario' desde el panel web")
        print()
        
    else:
        error = response.json()
        print("❌ ERROR AL CREAR USUARIO")
        print("=" * 70)
        print(f"Status: {response.status_code}")
        print(f"Detalle: {error.get('detail', 'Error desconocido')}")
        print()
        print("Posibles causas:")
        print("- La contraseña no cumple los requisitos (8+ caracteres)")
        print("- El username ya existe")
        print("- Problema de conexión a Cosmos DB")
        print()
        print("Respuesta completa:")
        print(json.dumps(error, indent=2))
        
except requests.exceptions.Timeout:
    print("❌ TIMEOUT")
    print()
    print("El servidor tardó demasiado en responder.")
    print("Esto puede suceder si Render.com está en cold start.")
    print("Espera 1 minuto y vuelve a intentar.")
    
except Exception as e:
    print(f"❌ ERROR INESPERADO: {e}")
    print()
    print("Verifica:")
    print("1. Que el backend esté corriendo en Render.com")
    print("2. Que Cosmos DB esté disponible")
    print("3. Que las variables de entorno estén configuradas")

print()
print("=" * 70)
