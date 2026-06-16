# temp_backend/auth_models.py
"""
Modelos de datos para el sistema de autenticación y autorización.
Incluye usuarios, roles, permisos y auditoría.
"""

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum

# Definición de roles disponibles en el sistema
class UserRole(str, Enum):
    ADMIN = "admin"                    # Control total del sistema
    MEDICO = "medico"                  # Médicos generales
    NUTRICION = "nutricion"            # Nutriólogos
    PSICOLOGIA = "psicologia"          # Psicólogos
    ODONTOLOGIA = "odontologia"        # Odontólogos
    ENFERMERIA = "enfermeria"          # Personal de enfermería
    RECEPCION = "recepcion"            # Personal de recepción/citas
    SERVICIOS_ESTUDIANTILES = "servicios_estudiantiles"  # Servicios estudiantiles
    LECTURA = "lectura"                # Solo lectura (reportes/estadísticas)

# Instituciones UAGro (88 total - CRES, Clínicas, Facultades, Preparatorias, Rectoría)
class Campus(str, Enum):
    # CRES - Centros Regionales de Educación Superior (6)
    CRES_CRUZ_GRANDE = "cres-cruz-grande"
    CRES_ZUMPANGO = "cres-zumpango"
    CRES_TAXCO_VIEJO = "cres-taxco-viejo"
    CRES_HUAMUXTITLAN = "cres-huamuxtitlan"
    CRES_LLANO_LARGO = "cres-llano-largo"
    CRES_TECPAN = "cres-tecpan"
    
    # Clínicas Universitarias (4)
    CLINICA_CHILPANCINGO = "clinica-chilpancingo"
    CLINICA_ACAPULCO = "clinica-acapulco"
    CLINICA_IGUALA = "clinica-iguala"
    CLINICA_OMETEPEC = "clinica-ometepec"
    
    # Facultades (20)
    FAC_GOBIERNO = "fac-gobierno"
    FAC_ARQUITECTURA = "fac-arquitectura"
    FAC_QUIMICO = "fac-quimico"
    FAC_COMUNICACION = "fac-comunicacion"
    FAC_DERECHO_CHIL = "fac-derecho-chil"
    FAC_FILOSOFIA = "fac-filosofia"
    FAC_INGENIERIA = "fac-ingenieria"
    FAC_MATEMATICAS_CENTRO = "fac-matematicas-centro"
    FAC_CONTADURIA = "fac-contaduria"
    FAC_DERECHO_ACA = "fac-derecho-aca"
    FAC_ECOLOGIA = "fac-ecologia"
    FAC_ECONOMIA = "fac-economia"
    FAC_ENFERMERIA2 = "fac-enfermeria2"
    FAC_MATEMATICAS_SUR = "fac-matematicas-sur"
    FAC_LENGUAS = "fac-lenguas"
    FAC_MEDICINA = "fac-medicina"
    FAC_ODONTOLOGIA = "fac-odontologia"
    FAC_TURISMO = "fac-turismo"
    FAC_AGROPECUARIAS = "fac-agropecuarias"
    FAC_MATEMATICAS_NORTE = "fac-matematicas-norte"
    
    # Preparatorias (50)
    PREP_1 = "prep-1"
    PREP_2 = "prep-2"
    PREP_3 = "prep-3"
    PREP_4 = "prep-4"
    PREP_5 = "prep-5"
    PREP_6 = "prep-6"
    PREP_7 = "prep-7"
    PREP_8 = "prep-8"
    PREP_9 = "prep-9"
    PREP_10 = "prep-10"
    PREP_11 = "prep-11"
    PREP_12 = "prep-12"
    PREP_13 = "prep-13"
    PREP_14 = "prep-14"
    PREP_15 = "prep-15"
    PREP_16 = "prep-16"
    PREP_17 = "prep-17"
    PREP_18 = "prep-18"
    PREP_19 = "prep-19"
    PREP_20 = "prep-20"
    PREP_21 = "prep-21"
    PREP_22 = "prep-22"
    PREP_23 = "prep-23"
    PREP_24 = "prep-24"
    PREP_25 = "prep-25"
    PREP_26 = "prep-26"
    PREP_27 = "prep-27"
    PREP_28 = "prep-28"
    PREP_29 = "prep-29"
    PREP_30 = "prep-30"
    PREP_31 = "prep-31"
    PREP_32 = "prep-32"
    PREP_33 = "prep-33"
    PREP_34 = "prep-34"
    PREP_35 = "prep-35"
    PREP_36 = "prep-36"
    PREP_37 = "prep-37"
    PREP_38 = "prep-38"
    PREP_39 = "prep-39"
    PREP_40 = "prep-40"
    PREP_41 = "prep-41"
    PREP_42 = "prep-42"
    PREP_43 = "prep-43"
    PREP_44 = "prep-44"
    PREP_45 = "prep-45"
    PREP_46 = "prep-46"
    PREP_47 = "prep-47"
    PREP_48 = "prep-48"
    PREP_49 = "prep-49"
    PREP_50 = "prep-50"
    
    # Rectoría y Coordinaciones Regionales (8)
    RECTORIA = "rectoria"
    COORD_SUR = "coord-sur"
    COORD_CENTRO = "coord-centro"
    COORD_NORTE = "coord-norte"
    COORD_COSTA_CHICA = "coord-costa-chica"
    COORD_COSTA_GRANDE = "coord-costa-grande"
    COORD_MONTANA = "coord-montana"
    COORD_TIERRA_CALIENTE = "coord-tierra-caliente"

# Modelo para crear un nuevo usuario
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Nombre de usuario único")
    email: EmailStr = Field(..., description="Correo electrónico institucional")
    password: str = Field(..., min_length=8, description="Contraseña (mínimo 8 caracteres)")
    nombre_completo: str = Field(..., min_length=3, description="Nombre completo del usuario")
    rol: UserRole = Field(..., description="Rol del usuario en el sistema")
    campus: Campus = Field(..., description="Campus al que pertenece")
    departamento: str = Field(..., description="Departamento o área de trabajo")
    
    @validator('password')
    def truncate_password(cls, v):
        """Truncar contraseña a 72 bytes para bcrypt si es necesario."""
        password_bytes = v.encode('utf-8')
        if len(password_bytes) > 72:
            v = password_bytes[:72].decode('utf-8', errors='ignore')
        return v

# Modelo de usuario en la base de datos
class UserInDB(BaseModel):
    id: str = Field(..., description="ID único: user:{username}@{campus}")
    username: str
    email: str
    password_hash: str  # Contraseña hasheada con bcrypt
    nombre_completo: str
    rol: UserRole
    campus: Campus
    departamento: str
    activo: bool = True
    fecha_creacion: str  # ISO 8601 timestamp
    ultimo_acceso: Optional[str] = None
    intentos_fallidos: int = 0
    bloqueado_hasta: Optional[str] = None

# Modelo de respuesta (sin contraseña)
class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    nombre_completo: str
    rol: UserRole
    campus: Campus
    departamento: str
    activo: bool
    fecha_creacion: str
    ultimo_acceso: Optional[str] = None

# Modelo para login
class LoginRequest(BaseModel):
    username: str = Field(..., description="Usuario o email")
    password: str = Field(..., description="Contraseña")
    campus: Optional[Campus] = None  # Opcional, se puede inferir

# Modelo de token JWT
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

# Modelo de datos del token (payload)
class TokenData(BaseModel):
    username: str
    rol: UserRole
    campus: Campus
    exp: Optional[datetime] = None

# Modelo para actualizar usuario
class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    nombre_completo: Optional[str] = None
    rol: Optional[UserRole] = None
    departamento: Optional[str] = None
    activo: Optional[bool] = None

# Modelo para cambiar contraseña
class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)

# Modelo de auditoría
class AuditAction(str, Enum):
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILED = "LOGIN_FAILED"
    CREATE_CARNET = "CREATE_CARNET"
    UPDATE_CARNET = "UPDATE_CARNET"
    VIEW_CARNET = "VIEW_CARNET"
    CREATE_NOTA = "CREATE_NOTA"
    UPDATE_NOTA = "UPDATE_NOTA"
    VIEW_NOTA = "VIEW_NOTA"
    CREATE_CITA = "CREATE_CITA"
    UPDATE_CITA = "UPDATE_CITA"
    DELETE_CITA = "DELETE_CITA"
    CREATE_PROMOCION = "CREATE_PROMOCION"
    CREATE_VACCINATION = "CREATE_VACCINATION"
    CREATE_USER = "CREATE_USER"
    UPDATE_USER = "UPDATE_USER"
    DELETE_USER = "DELETE_USER"

class AuditLog(BaseModel):
    id: str  # audit:{timestamp}-{random}
    usuario: str  # username@campus
    accion: AuditAction
    recurso: Optional[str] = None  # ID del recurso afectado
    detalles: Optional[str] = None
    timestamp: str  # ISO 8601
    ip: Optional[str] = None
    user_agent: Optional[str] = None

# Permisos por rol (definición de políticas)
ROLE_PERMISSIONS = {
    UserRole.ADMIN: [
        "users:create", "users:read", "users:update", "users:delete",
        "carnets:create", "carnets:read", "carnets:update", "carnets:delete",
        "notas:create", "notas:read", "notas:update", "notas:delete",
        "citas:create", "citas:read", "citas:update", "citas:delete",
        "promociones:create", "promociones:read",
        "vaccination:create", "vaccination:read", "vaccination:update",
        "tickets:create", "tickets:read", "tickets:reply", "tickets:assign",
        "tickets:update_status", "tickets:manage",
        "audit:read", "reports:read"
    ],
    UserRole.MEDICO: [
        "carnets:create", "carnets:read", "carnets:update",
        "notas:create", "notas:read", "notas:update",
        "citas:create", "citas:read", "citas:update",
        "vaccination:create", "vaccination:read", "vaccination:update",
        "tickets:create", "tickets:read", "tickets:reply",
        "tickets:assign", "tickets:update_status"
    ],
    UserRole.NUTRICION: [
        "carnets:create", "carnets:read", "carnets:update",
        "notas:create", "notas:read", "notas:update",
        "citas:create", "citas:read", "citas:update",
        "vaccination:create", "vaccination:read", "vaccination:update",
        "tickets:create", "tickets:read", "tickets:reply",
        "tickets:assign", "tickets:update_status"
    ],
    UserRole.PSICOLOGIA: [
        "carnets:create", "carnets:read", "carnets:update",
        "notas:create", "notas:read", "notas:update",
        "citas:create", "citas:read", "citas:update",
        "vaccination:create", "vaccination:read", "vaccination:update",
        "tickets:create", "tickets:read", "tickets:reply",
        "tickets:assign", "tickets:update_status"
    ],
    UserRole.ODONTOLOGIA: [
        "carnets:create", "carnets:read", "carnets:update",
        "notas:create", "notas:read", "notas:update",
        "citas:create", "citas:read", "citas:update",
        "vaccination:create", "vaccination:read", "vaccination:update",
        "tickets:create", "tickets:read", "tickets:reply",
        "tickets:assign", "tickets:update_status"
    ],
    UserRole.ENFERMERIA: [
        "carnets:create", "carnets:read", "carnets:update",
        "notas:create", "notas:read", "notas:update",
        "citas:create", "citas:read", "citas:update",
        "vaccination:create", "vaccination:read", "vaccination:update",
        "tickets:create", "tickets:read", "tickets:reply",
        "tickets:assign", "tickets:update_status"
    ],
    UserRole.RECEPCION: [
        "carnets:create", "carnets:read", "carnets:update",
        "notas:create", "notas:read", "notas:update",
        "citas:create", "citas:read", "citas:update",
        "vaccination:create", "vaccination:read", "vaccination:update",
        "tickets:create", "tickets:read", "tickets:reply",
        "tickets:assign", "tickets:update_status"
    ],
    UserRole.SERVICIOS_ESTUDIANTILES: [
        "carnets:create", "carnets:read", "carnets:update",
        "notas:create", "notas:read", "notas:update",
        "citas:create", "citas:read", "citas:update",
        "promociones:create", "promociones:read",
        "vaccination:create", "vaccination:read", "vaccination:update",
        "tickets:create", "tickets:read", "tickets:reply",
        "tickets:assign", "tickets:update_status"
    ],
    UserRole.LECTURA: [
        "carnets:read",
        "tickets:read",
        "reports:read"
    ]
}

def has_permission(rol: UserRole, permission: str) -> bool:
    """Verifica si un rol tiene un permiso específico."""
    return permission in ROLE_PERMISSIONS.get(rol, [])
