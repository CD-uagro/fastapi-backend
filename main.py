# DEBUG: Use stderr to force output in Gunicorn logs
import sys
import subprocess
import os
from datetime import datetime

sys.stderr.write("=" * 80 + "\n")
sys.stderr.write("FASTAPI MAIN.PY LOADING - Checking for /carnet/search endpoint\n")
sys.stderr.flush()
try:
    commit_hash = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], 
                                        cwd=os.path.dirname(os.path.abspath(__file__))).decode().strip()
    sys.stderr.write(f"   Git commit: {commit_hash}\n")
except Exception as e:
    sys.stderr.write(f"   Git commit: unknown ({e})\n")
sys.stderr.write(f"   Time: {datetime.now().isoformat()}\n")
sys.stderr.write("=" * 80 + "\n")
sys.stderr.flush()

# Sistema de Autenticación CRES - v1.1
from fastapi import FastAPI, HTTPException, Body, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from cosmos_helper import CosmosDBHelper
from azure.cosmos.exceptions import CosmosHttpResponseError
from dotenv import load_dotenv
from typing import Optional
import uuid
import json

# Importar router de actualizaciones
from update_routes import router as updates_router

# Importar modelos y servicios de autenticación
from auth_models import (
    UserCreate, UserResponse, UserInDB, UserUpdate, LoginRequest, Token, 
    UserRole, Campus, AuditLog, AuditAction
)
from auth_service import (
    AuthService, get_current_user, require_role, require_permission,
    is_user_locked, should_lock_user, calculate_lockout_time,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

load_dotenv()

app = FastAPI()

sys.stderr.write("=" * 80 + "\n")
sys.stderr.write("FASTAPI APP CREATED SUCCESSFULLY\n")
sys.stderr.write("=" * 80 + "\n")
sys.stderr.flush()

# CORS para permitir requests del frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montar router de actualizaciones
app.include_router(updates_router)

carnets = CosmosDBHelper(
    os.environ["COSMOS_CONTAINER_CARNETS"], "/id"
)
notas = CosmosDBHelper(
    os.environ["COSMOS_CONTAINER_NOTAS"], "/matricula"
)
promociones_salud = CosmosDBHelper(
    os.environ.get("COSMOS_CONTAINER_PROMOCIONES_SALUD", "promociones_salud"), "/id"
)

# Helper para tarjeta de vacunación individual (aplicaciones por estudiante)
# Contenedor: Tarjeta_vacunacion, Partition Key: /matricula
# Solo se guardan aplicaciones individuales, NO campañas (campañas son solo locales)
tarjeta_vacunacion = CosmosDBHelper(
    os.environ.get("COSMOS_CONTAINER_VACUNACION", "Tarjeta_vacunacion"), "/matricula"
)

# Nota: Las campañas de vacunación NO se guardan en Cosmos DB
# Se manejan localmente en el frontend y solo se genera PDF

# Handlers directos para citas (contenedor citas_ida exclusivamente)
from cosmos_helper import get_citas_container, get_citas_pk_path, upsert_cita

# Modelo para las notas (campos opcionales con alias)
class NotaModel(BaseModel):
    id: Optional[str] = None
    matricula: str
    departamento: str
    cuerpo: str
    tratante: Optional[str] = ""
    createdAt: Optional[str] = None
    
    class Config:
        populate_by_name = True

# Modelo para los carnets (campos opcionales con alias)
class CarnetModel(BaseModel):
    id: Optional[str] = None
    matricula: str
    nombreCompleto: Optional[str] = ""
    correo: Optional[str] = ""
    edad: Optional[int] = 0
    sexo: Optional[str] = ""
    categoria: Optional[str] = ""
    programa: Optional[str] = ""
    tipoSangre: Optional[str] = ""
    enfermedadCronica: Optional[str] = ""
    unidadMedica: Optional[str] = ""
    numeroAfiliacion: Optional[str] = ""
    usoSeguroUniversitario: Optional[str] = ""
    donante: Optional[str] = ""
    emergenciaContacto: Optional[str] = ""
    # Campos adicionales del formulario Flutter
    discapacidad: Optional[str] = ""
    tipoDiscapacidad: Optional[str] = ""
    alergias: Optional[str] = ""
    emergenciaTelefono: Optional[str] = ""
    expedienteNotas: Optional[str] = ""
    expedienteAdjuntos: Optional[str] = "[]"
    
    class Config:
        populate_by_name = True

# Modelo para promociones de salud
class PromocionSaludModel(BaseModel):
    id: Optional[str] = None
    link: str
    departamento: str
    categoria: str
    programa: str
    matricula: Optional[str] = ""  # Matrícula del alumno (opcional)
    destinatario: str  # "alumno" o "general"
    autorizado: Optional[bool] = False
    createdAt: Optional[str] = None
    createdBy: Optional[str] = ""  # Usuario que creó la promoción
    
    class Config:
        populate_by_name = True

# ============================================
# MODELOS DE VACUNACIÓN
# ============================================

# Modelo para campañas de vacunación
class VaccinationCampaignModel(BaseModel):
    id: Optional[str] = None
    nombre: str  # Nombre de la campaña
    descripcion: Optional[str] = ""
    vacuna: str  # Tipo de vacuna aplicada en esta campaña
    fechaInicio: str  # Fecha de inicio de la campaña
    fechaFin: Optional[str] = None  # Fecha de fin (opcional)
    activa: Optional[bool] = True  # Estado de la campaña
    createdAt: Optional[str] = None
    createdBy: Optional[str] = ""  # Usuario que creó la campaña
    totalAplicadas: Optional[int] = 0  # Contador de vacunas aplicadas
    
    class Config:
        populate_by_name = True

# Modelo para registros de vacunación
class VaccinationRecordModel(BaseModel):
    id: Optional[str] = None
    campanaId: str  # ID de la campaña de vacunación
    campanaNombre: Optional[str] = ""  # Nombre de la campaña (denormalizado)
    matricula: str  # Matrícula del estudiante
    nombreEstudiante: Optional[str] = ""  # Nombre del estudiante (opcional)
    vacuna: str  # Vacuna aplicada
    dosis: Optional[int] = 1  # Número de dosis (1, 2, 3, etc.)
    lote: Optional[str] = ""  # Lote de la vacuna
    aplicadoPor: Optional[str] = ""  # Nombre del aplicador
    observaciones: Optional[str] = ""
    fechaAplicacion: str  # Fecha en que se aplicó la vacuna
    createdAt: Optional[str] = None
    
    class Config:
        populate_by_name = True

@app.get("/carnet/{id}")
def get_carnet(id: str):
    # Normalizar id: si no empieza con carnet:, agregar prefijo
    normalized_id = id if id.startswith("carnet:") else f"carnet:{id}"
    
    # Intento A: lectura directa por id normalizado
    try:
        data = carnets.get_by_id(normalized_id)
        return data
    except CosmosHttpResponseError as e:
        # Intento B: Si NotFound → query por matricula excluyendo citas
        if e.status_code == 404:
            try:
                results = carnets.query_items(
                    """SELECT TOP 1 * FROM c 
                       WHERE c.matricula = @m 
                         AND NOT STARTSWITH(c.id, 'cita:')
                         AND NOT IS_DEFINED(c.inicio)
                         AND NOT IS_DEFINED(c.fin)
                       ORDER BY c._ts DESC""",
                    params=[{"name": "@m", "value": id}]
                )
                
                if results:
                    return results[0]
                else:
                    raise HTTPException(status_code=404, detail={"code": 404, "message": "Carnet no encontrado"})
                    
            except CosmosHttpResponseError as fallback_error:
                raise HTTPException(status_code=fallback_error.status_code or 500, detail={"code": fallback_error.status_code or 500, "message": fallback_error.message or "Error en query"})
        else:
            raise HTTPException(status_code=e.status_code or 500, detail={"code": e.status_code or 500, "message": e.message or "Error en cosmos"})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(e)})

@app.get("/carnet/search")
def search_carnet_by_name(nombre: str):
    """Busca carnets por nombre (búsqueda parcial case-insensitive)"""
    print(f"ENDPOINT /carnet/search CALLED with nombre={nombre}")
    try:
        # Búsqueda con CONTAINS y UPPER para case-insensitive
        results = carnets.query_items(
            """SELECT TOP 10 * FROM c 
               WHERE CONTAINS(UPPER(c.nombreCompleto), UPPER(@nombre))
                 AND NOT STARTSWITH(c.id, 'cita:')
                 AND NOT IS_DEFINED(c.inicio)
                 AND NOT IS_DEFINED(c.fin)
               ORDER BY c._ts DESC""",
            params=[{"name": "@nombre", "value": nombre}]
        )
        
        if results:
            # Retornar el primer resultado (más reciente)
            return results[0]
        else:
            raise HTTPException(status_code=404, detail={
                "code": 404, 
                "message": f"No se encontró carnet con nombre '{nombre}'"
            })
            
    except CosmosHttpResponseError as e:
        raise HTTPException(
            status_code=e.status_code, 
            detail={"code": e.status_code, "message": e.message}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(e)})

@app.get("/notas/{matricula}")
def get_notas(matricula: str):
    try:
        result = notas.query_items(
            "SELECT * FROM c WHERE c.matricula=@m ORDER BY c.createdAt DESC",
            params=[{"name": "@m", "value": matricula}]
        )
        return result
    except CosmosHttpResponseError as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.status_code, "message": e.message})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(e)})

@app.post("/notas/")
@app.post("/notas")  # Alias sin slash final
def create_nota(nota: NotaModel = Body(...)):
    try:
        # Auto-generar campos si no se proporcionan
        nota_dict = nota.dict()
        if not nota_dict.get("id"):
            nota_dict["id"] = f"nota:{uuid.uuid4()}"
        if not nota_dict.get("createdAt"):
            nota_dict["createdAt"] = datetime.utcnow().isoformat() + "Z"
        
        # Cosmos: PK = /matricula
        res = notas.upsert_item(nota_dict, partition_value=nota.matricula)
        
        return {"status": "created", "data": res, "id": nota_dict["id"]}
    except CosmosHttpResponseError as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.status_code, "message": e.message})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(e)})

# Endpoint para crear carnets (con rutas alternativas) - TODOS LOS USUARIOS AUTENTICADOS
@app.post("/carnet/")
@app.post("/carnet")  # Alias sin slash final
async def create_carnet(
    carnet: CarnetModel = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Crear nuevo carnet de salud.
    PERMITIDO: Todos los usuarios autenticados pueden crear carnets.
    """
    try:
        # Verificar que NO tenga ID (es creación nueva)
        carnet_dict = carnet.dict()
        if carnet_dict.get("id"):
            raise HTTPException(
                status_code=400, 
                detail="Para editar un carnet existente use PUT /carnet/{id}"
            )
        
        # Auto-generar ID para nuevo carnet
        carnet_dict["id"] = f"carnet:{uuid.uuid4()}"
        
        # Cosmos: PK = /id
        res = carnets.upsert_item(carnet_dict, partition_value=carnet_dict["id"])
        
        # Auditoría
        log_audit(
            current_user.username if hasattr(current_user, 'username') else "unknown",
            AuditAction.CREATE_CARNET,
            recurso=carnet_dict["id"],
            detalles=f"Carnet creado para matrícula: {carnet.matricula}"
        )
        
        return {"status": "created", "data": res, "id": carnet_dict["id"]}
    except CosmosHttpResponseError as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.status_code, "message": e.message})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(e)})

# Endpoint para editar carnets existentes - TODOS LOS USUARIOS AUTENTICADOS
@app.put("/carnet/{carnet_id}")
async def update_carnet(
    carnet_id: str,
    carnet: CarnetModel = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Editar carnet de salud existente.
    PERMITIDO: Todos los usuarios autenticados pueden editar carnets.
    """
    try:
        # Verificar que el carnet existe
        try:
            existing = carnets.read_item(carnet_id, carnet_id)
        except:
            raise HTTPException(status_code=404, detail="Carnet no encontrado")
        
        # Preparar datos actualizados manteniendo el ID original
        carnet_dict = carnet.dict()
        carnet_dict["id"] = carnet_id  # Forzar ID original
        
        # Actualizar en Cosmos
        res = carnets.upsert_item(carnet_dict, partition_value=carnet_id)
        
        # Auditoría
        log_audit(
            current_user.username if hasattr(current_user, 'username') else "unknown",
            AuditAction.UPDATE_CARNET,
            recurso=carnet_id,
            detalles=f"Carnet editado para matrícula: {carnet.matricula}"
        )
        
        return {"status": "updated", "data": res, "id": carnet_id}
    except CosmosHttpResponseError as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.status_code, "message": e.message})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(e)})

# Alias de expediente para compatibilidad con Flutter
@app.get("/expediente/matricula/{matricula}")
def get_expediente_by_matricula(matricula: str):
    """Alias para búsqueda de carnet por matrícula"""
    return get_carnet(matricula)

@app.get("/expediente/{id}")
def get_expediente_by_id(id: str):
    """Alias para búsqueda de carnet por ID"""
    return get_carnet(id)

# Endpoint adicional para compatibilidad con Flutter (rutas originales)
@app.options("/notas")
@app.options("/notas/")
@app.options("/carnet")
@app.options("/carnet/")
def handle_options():
    return {"message": "OK"}

# Health check para verificar conectividad
@app.get("/health")
def health_check():
    try:
        # Test básico de conectividad a Cosmos
        test_query = notas.query_items("SELECT TOP 1 * FROM c")
        return {
            "status": "healthy",
            "cosmos_connected": True,
            "containers": {
                "carnets": os.environ.get("COSMOS_CONTAINER_CARNETS", "unknown"),
                "notas": os.environ.get("COSMOS_CONTAINER_NOTAS", "unknown")
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy", 
            "error": str(e),
            "cosmos_connected": False
        }


@app.get("/_diag/citas")
def diagnose_citas():
    """Endpoint de diagnóstico para verificar configuración de citas (solo con DEBUG_CITAS)"""
    # Solo permitir acceso si DEBUG_CITAS está activado
    if os.environ.get("DEBUG_CITAS", "false").lower() != "true":
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Endpoint no encontrado"})
    
    try:
        from cosmos_helper import get_citas_container, get_citas_pk_path
        
        # Obtener configuración
        db_name = os.environ.get("COSMOS_DB", "NOT_SET")
        container_name = os.environ.get("COSMOS_CONTAINER_CITAS", "NOT_SET")
        pk_path = os.environ.get("COSMOS_PK_CITAS", "NOT_SET")
        
        # Probar conectividad
        can_read = False
        try:
            container = get_citas_container()
            # Test con query simple
            list(container.query_items("SELECT TOP 1 * FROM c", enable_cross_partition_query=True))
            can_read = True
        except Exception as e:
            if os.environ.get("DEBUG_CITAS", "false").lower() == "true":
                print(f"[DIAG] Error testing citas container: {e}")
        
        return {
            "db": db_name,
            "container": container_name,
            "pk_path": pk_path,
            "can_read": can_read
        }
    except Exception as e:
        return {
            "error": str(e),
            "db": os.environ.get("COSMOS_DB", "NOT_SET"),
            "container": os.environ.get("COSMOS_CONTAINER_CITAS", "NOT_SET"),
            "pk_path": os.environ.get("COSMOS_PK_CITAS", "NOT_SET"),
            "can_read": False
        }


# === RUTAS DE CITAS (contenedor citas_ida exclusivamente) ===

class CitaModel(BaseModel):
    id: Optional[str] = None
    matricula: str
    inicio: str  # ISO datetime
    fin: str     # ISO datetime
    motivo: str
    departamento: Optional[str] = ""
    estado: Optional[str] = "programada"
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

@app.post("/citas")
def create_cita(cita: CitaModel):
    try:
        # Lazy init: obtener contenedor dentro del handler
        container = get_citas_container()
        
        cita_dict = cita.dict()
        
        # Validar mínimos
        if not all([cita_dict.get("matricula"), cita_dict.get("inicio"), 
                   cita_dict.get("fin"), cita_dict.get("motivo")]):
            raise HTTPException(status_code=400, detail="Campos requeridos: matricula, inicio, fin, motivo")
        
        # Usar helper exclusivo para citas
        result = upsert_cita(cita_dict)
        
        return {"status": "created", "data": result}
        
    except Exception as cosmos_error:
        if "Error connecting to citas container" in str(cosmos_error):
            # Error de configuración/credenciales: devolver 503
            return JSONResponse(
                status_code=503,
                content={"error": "citas_unavailable", "detail": str(cosmos_error)}
            )
        # Otros errores
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(cosmos_error)})

@app.get("/citas/{cita_id}")
def get_cita_by_id(cita_id: str):
    try:
        # Lazy init: obtener contenedor dentro del handler
        container = get_citas_container()
        pk_path = get_citas_pk_path()
        
        if pk_path == "/id":
            # Leer directo por partition key
            result = container.read_item(item=cita_id, partition_key=cita_id)
        else:
            # Query cross-partition
            query = "SELECT * FROM c WHERE c.id = @id"
            params = [{"name": "@id", "value": cita_id}]
            results = list(container.query_items(
                query=query, 
                parameters=params, 
                enable_cross_partition_query=True
            ))
            if not results:
                raise HTTPException(status_code=404, detail={"code": 404, "message": "Cita no encontrada"})
            result = results[0]
        
        return result
        
    except Exception as cosmos_error:
        if "Error connecting to citas container" in str(cosmos_error):
            # Error de configuración/credenciales: devolver 503
            return JSONResponse(
                status_code=503,
                content={"error": "citas_unavailable", "detail": str(cosmos_error)}
            )
        elif "404" in str(cosmos_error) or "not found" in str(cosmos_error).lower():
            raise HTTPException(status_code=404, detail={"code": 404, "message": "Cita no encontrada"})
        # Otros errores
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(cosmos_error)})

@app.get("/citas/por-matricula/{matricula}")
def get_citas_by_matricula(matricula: str):
    try:
        # Lazy init: obtener contenedor dentro del handler
        container = get_citas_container()
        
        # Query siempre en cita_id
        query = "SELECT * FROM c WHERE c.matricula = @m ORDER BY c._ts DESC"
        params = [{"name": "@m", "value": matricula}]
        
        results = list(container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        return results
        
    except Exception as cosmos_error:
        if "Error connecting to citas container" in str(cosmos_error):
            # Error de configuración/credenciales: devolver 503
            return JSONResponse(
                status_code=503,
                content={"error": "citas_unavailable", "detail": str(cosmos_error)}
            )
        # Otros errores
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(cosmos_error)})

# Endpoints para promociones de salud
@app.post("/promociones-salud/")
@app.post("/promociones-salud")
def create_promocion_salud(promocion: PromocionSaludModel = Body(...)):
    """Crear una nueva promoción de salud"""
    try:
        # Auto-generar campos si no se proporcionan
        promocion_dict = promocion.dict()
        if not promocion_dict.get("id"):
            promocion_dict["id"] = f"promocion:{uuid.uuid4()}"
        if not promocion_dict.get("createdAt"):
            promocion_dict["createdAt"] = datetime.utcnow().isoformat() + "Z"
        
        # Cosmos: PK = /id
        res = promociones_salud.upsert_item(promocion_dict, partition_value=promocion_dict["id"])
        return res
    except CosmosHttpResponseError as e:
        raise HTTPException(status_code=e.status_code or 500, detail={"code": e.status_code or 500, "message": e.message or "Error en cosmos"})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(e)})

@app.get("/promociones-salud/")
def get_promociones_salud():
    """Obtener todas las promociones de salud"""
    try:
        result = promociones_salud.query_items(
            "SELECT * FROM c ORDER BY c.createdAt DESC"
        )
        return result
    except CosmosHttpResponseError as e:
        raise HTTPException(status_code=e.status_code or 500, detail={"code": e.status_code or 500, "message": e.message or "Error en cosmos"})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 500, "message": str(e)})

@app.post("/promociones-salud/validate-supervisor")
def validate_supervisor_key(key_data: dict = Body(...)):
    """Validar clave de supervisor"""
    supervisor_key = key_data.get("key", "")
    valid_key = "UAGROcres2025"
    
    if supervisor_key == valid_key:
        return {"valid": True, "message": "Clave válida"}
    else:
        return {"valid": False, "message": "Clave incorrecta"}

# ============================================
# ENDPOINTS DE VACUNACIÓN (DESHABILITADOS)
# ============================================
# NOTA: Las campañas de vacunación se manejan SOLO localmente en el frontend.
# No se guardan en Cosmos DB. Solo se genera PDF local.
# Los únicos endpoints activos son los de aplicaciones individuales (/carnet/{matricula}/vacunacion)

# @app.post("/vaccination-campaigns/")
# @app.post("/vaccination-campaigns")
# def create_vaccination_campaign(campaign: VaccinationCampaignModel = Body(...)):
#     """[DESHABILITADO] Las campañas se manejan localmente"""
#     raise HTTPException(status_code=501, detail="Endpoint deshabilitado. Las campañas se manejan localmente.")

# @app.get("/vaccination-campaigns/")
# def get_vaccination_campaigns():
#     """[DESHABILITADO] Las campañas se manejan localmente"""
#     raise HTTPException(status_code=501, detail="Endpoint deshabilitado. Las campañas se manejan localmente.")

# @app.get("/vaccination-campaigns/{campaign_id}")
# def get_vaccination_campaign(campaign_id: str):
#     """[DESHABILITADO] Las campañas se manejan localmente"""
#     raise HTTPException(status_code=501, detail="Endpoint deshabilitado. Las campañas se manejan localmente.")

# @app.post("/vaccination-records/")
# @app.post("/vaccination-records")
# def create_vaccination_record(record: VaccinationRecordModel = Body(...)):
#     """[DESHABILITADO] Los registros se asocian directamente al estudiante"""
#     raise HTTPException(status_code=501, detail="Endpoint deshabilitado. Usar /carnet/{matricula}/vacunacion")

# @app.get("/vaccination-records/campaign/{campaign_id}")
# def get_vaccination_records_by_campaign(campaign_id: str):
#     """[DESHABILITADO] Los registros se consultan por matrícula"""
#     raise HTTPException(status_code=501, detail="Endpoint deshabilitado. Usar /carnet/{matricula}/vacunacion")

# @app.get("/vaccination-records/matricula/{matricula}")
# def get_vaccination_records_by_matricula(matricula: str):
#     """[DESHABILITADO] Usar el endpoint correcto del carnet"""
#     raise HTTPException(status_code=501, detail="Endpoint deshabilitado. Usar /carnet/{matricula}/vacunacion")


# ============================================================================
# ENDPOINTS DE AUTENTICACIÓN Y AUTORIZACIÓN
# ============================================================================

# Helper para contenedor de usuarios
usuarios = CosmosDBHelper(
    os.environ.get("COSMOS_CONTAINER_USUARIOS", "usuarios"), "/id"
)

# Helper para auditoría
auditoria = CosmosDBHelper(
    os.environ.get("COSMOS_CONTAINER_AUDITORIA", "auditoria"), "/id"
)

def log_audit(usuario: str, accion: AuditAction, recurso: Optional[str] = None, detalles: Optional[str] = None, ip: Optional[str] = None):
    """Registra una acción en el log de auditoría."""
    try:
        audit_id = f"audit:{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        log_entry = {
            "id": audit_id,
            "usuario": usuario,
            "accion": accion.value,
            "recurso": recurso,
            "detalles": detalles,
            "timestamp": datetime.utcnow().isoformat(),
            "ip": ip
        }
        auditoria.create_item(log_entry)
        print(f"📝 Auditoría: {usuario} → {accion.value}")
    except Exception as e:
        print(f"⚠️ Error al registrar auditoría: {e}")

def ensure_auth_containers():
    """
    Verifica y crea los contenedores de autenticación si no existen.
    Esto permite el bootstrap automático del sistema.
    """
    from azure.cosmos import CosmosClient, PartitionKey
    
    try:
        cosmos_url = os.environ["COSMOS_URL"]
        cosmos_key = os.environ["COSMOS_KEY"]
        db_name = os.environ["COSMOS_DB"]
        
        client = CosmosClient(cosmos_url, credential=cosmos_key)
        database = client.get_database_client(db_name)
        
        # Obtener lista de contenedores existentes
        existing_containers = {c['id'] for c in database.list_containers()}
        print(f"📦 Contenedores existentes: {existing_containers}")
        
        # Crear contenedor 'usuarios' si no existe
        if "usuarios" not in existing_containers:
            try:
                database.create_container(
                    id="usuarios",
                    partition_key=PartitionKey(path="/id"),
                    offer_throughput=400
                )
                print("✅ Contenedor 'usuarios' creado")
            except Exception as e:
                error_msg = str(e)
                if "Conflict" in error_msg or "409" in error_msg:
                    print("ℹ️  Contenedor 'usuarios' ya existe (conflict)")
                else:
                    print(f"⚠️ Error creando 'usuarios': {error_msg}")
                    raise
        else:
            print("ℹ️  Contenedor 'usuarios' ya existe")
        
        # Crear contenedor 'auditoria' si no existe
        if "auditoria" not in existing_containers:
            try:
                database.create_container(
                    id="auditoria",
                    partition_key=PartitionKey(path="/id"),
                    offer_throughput=400
                )
                print("✅ Contenedor 'auditoria' creado")
            except Exception as e:
                error_msg = str(e)
                if "Conflict" in error_msg or "409" in error_msg:
                    print("ℹ️  Contenedor 'auditoria' ya existe (conflict)")
                else:
                    print(f"⚠️ Error creando 'auditoria': {error_msg}")
                    raise
        else:
            print("ℹ️  Contenedor 'auditoria' ya existe")
            
    except Exception as e:
        print(f"❌ Error en ensure_auth_containers: {e}")
        import traceback
        traceback.print_exc()
        raise

@app.post("/auth/init-admin", response_model=UserResponse, tags=["Autenticación"])
async def initialize_first_admin(user: UserCreate):
    """
    Endpoint especial para crear el PRIMER usuario administrador del sistema.
    Este endpoint se desactiva automáticamente después de crear el primer admin.
    Solo funciona si NO existe ningún usuario admin en el sistema.
    
    **IMPORTANTE:** Por seguridad, este endpoint debe deshabilitarse en producción
    después de crear el primer admin.
    """
    try:
        # Asegurar que existan los contenedores de autenticación
        ensure_auth_containers()
        
        # Verificar si ya existe algún admin
        query = "SELECT * FROM c WHERE c.rol = 'admin' AND STARTSWITH(c.id, 'user:')"
        existing_admins = usuarios.query_items(query, None)
        
        if existing_admins and len(existing_admins) > 0:
            raise HTTPException(
                status_code=403,
                detail="El sistema ya tiene un administrador. Use /auth/register con credenciales de admin."
            )
        
        # Solo permitir crear admin
        if user.rol != UserRole.ADMIN:
            raise HTTPException(
                status_code=400,
                detail="Este endpoint solo permite crear el primer administrador"
            )
        
        # Validar fortaleza de la contraseña
        is_valid, message = AuthService.validate_password_strength(user.password)
        if not is_valid:
            raise HTTPException(status_code=400, detail=message)
        
        # Generar ID único
        user_id = AuthService.generate_user_id(user.username, user.campus)
        
        # Crear usuario admin
        user_dict = {
            "id": user_id,
            "username": user.username,
            "email": user.email,
            "password_hash": AuthService.hash_password(user.password),
            "nombre_completo": user.nombre_completo,
            "rol": user.rol.value,
            "campus": user.campus.value,
            "departamento": user.departamento,
            "activo": True,
            "fecha_creacion": datetime.utcnow().isoformat(),
            "ultimo_acceso": None,
            "intentos_fallidos": 0,
            "bloqueado_hasta": None
        }
        
        usuarios.create_item(user_dict)
        
        # Auditoría
        log_audit(
            user.username,
            AuditAction.CREATE_USER,
            recurso=user_id,
            detalles="Primer administrador del sistema creado",
            ip="system-init"
        )
        
        print(f"✅ Primer admin creado: {user.username}")
        
        user_response = UserResponse(**{k: v for k, v in user_dict.items() if k != "password_hash"})
        return user_response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al inicializar admin: {str(e)}")

@app.post("/auth/register", response_model=UserResponse, tags=["Autenticación"])
async def register_user(user: UserCreate, current_user: UserResponse = Depends(require_role(UserRole.ADMIN))):
    """
    Registrar un nuevo usuario en el sistema.
    Solo accesible para administradores.
    """
    try:
        # Validar fortaleza de la contraseña
        is_valid, message = AuthService.validate_password_strength(user.password)
        if not is_valid:
            raise HTTPException(status_code=400, detail=message)
        
        # Generar ID único
        user_id = AuthService.generate_user_id(user.username, user.campus)
        
        # Verificar si ya existe
        try:
            existing = usuarios.read_item(user_id, user_id)
            if existing:
                raise HTTPException(status_code=400, detail="El usuario ya existe")
        except:
            pass  # No existe, continuar
        
        # Crear usuario
        user_dict = {
            "id": user_id,
            "username": user.username,
            "email": user.email,
            "password_hash": AuthService.hash_password(user.password),
            "nombre_completo": user.nombre_completo,
            "rol": user.rol.value,
            "campus": user.campus.value,
            "departamento": user.departamento,
            "activo": True,
            "fecha_creacion": datetime.utcnow().isoformat(),
            "ultimo_acceso": None,
            "intentos_fallidos": 0,
            "bloqueado_hasta": None,
            "type": "user"
        }
        
        usuarios.create_item(user_dict)
        
        # Auditoría
        log_audit(
            current_user.username,
            AuditAction.CREATE_USER,
            user_id,
            f"Creó usuario {user.username} con rol {user.rol.value}"
        )
        
        # Retornar sin contraseña
        return UserResponse(**{k: v for k, v in user_dict.items() if k != "password_hash"})
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear usuario: {str(e)}")

@app.post("/auth/login", response_model=Token, tags=["Autenticación"])
async def login(request: Request, login_data: LoginRequest):
    """
    Iniciar sesión y obtener token JWT.
    """
    try:
        # Buscar usuario
        user_id = AuthService.generate_user_id(login_data.username, login_data.campus or Campus.LLANO_LARGO)
        
        try:
            user_dict = usuarios.read_item(user_id, user_id)
            user = UserInDB(**user_dict)
        except:
            # Log intento fallido
            log_audit(
                login_data.username,
                AuditAction.LOGIN_FAILED,
                detalles="Usuario no encontrado",
                ip=request.client.host if request.client else None
            )
            raise HTTPException(
                status_code=401,
                detail="Usuario o contraseña incorrectos"
            )
        
        # Verificar si está bloqueado
        if is_user_locked(user):
            raise HTTPException(
                status_code=403,
                detail=f"Usuario bloqueado temporalmente por múltiples intentos fallidos. Intente después de {user.bloqueado_hasta}"
            )
        
        # Verificar si está activo
        if not user.activo:
            raise HTTPException(
                status_code=403,
                detail="Usuario desactivado. Contacte al administrador."
            )
        
        # Verificar contraseña
        if not AuthService.verify_password(login_data.password, user.password_hash):
            # Incrementar intentos fallidos
            user_dict["intentos_fallidos"] = user.intentos_fallidos + 1
            
            if should_lock_user(user):
                user_dict["bloqueado_hasta"] = calculate_lockout_time()
                usuarios.upsert_item(user_dict, user_id)
                log_audit(
                    user.username,
                    AuditAction.LOGIN_FAILED,
                    detalles=f"Usuario bloqueado por {user.intentos_fallidos + 1} intentos fallidos",
                    ip=request.client.host if request.client else None
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Demasiados intentos fallidos. Usuario bloqueado por 30 minutos."
                )
            
            usuarios.upsert_item(user_dict, user_id)
            log_audit(
                user.username,
                AuditAction.LOGIN_FAILED,
                detalles=f"Contraseña incorrecta (intento {user.intentos_fallidos + 1})",
                ip=request.client.host if request.client else None
            )
            raise HTTPException(
                status_code=401,
                detail="Usuario o contraseña incorrectos"
            )
        
        # Login exitoso - resetear intentos fallidos y actualizar último acceso
        user_dict["intentos_fallidos"] = 0
        user_dict["bloqueado_hasta"] = None
        user_dict["ultimo_acceso"] = datetime.utcnow().isoformat()
        usuarios.upsert_item(user_dict, user_id)
        
        # Crear token
        access_token = AuthService.create_access_token(
            data={
                "sub": user.username,
                "rol": user.rol.value,
                "campus": user.campus.value
            },
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        # Auditoría
        log_audit(
            user.username,
            AuditAction.LOGIN,
            detalles=f"Login exitoso desde {request.client.host if request.client else 'unknown'}",
            ip=request.client.host if request.client else None
        )
        
        # Retornar token y datos del usuario
        user_response = UserResponse(**{k: v for k, v in user_dict.items() if k != "password_hash"})
        return Token(access_token=access_token, user=user_response)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en login: {str(e)}")

@app.get("/auth/me", response_model=UserResponse, tags=["Autenticación"])
async def get_current_user_info(current_user = Depends(get_current_user)):
    """
    Obtener información del usuario actual desde el token.
    """
    user_id = AuthService.generate_user_id(current_user.username, current_user.campus)
    user_dict = usuarios.read_item(user_id, user_id)
    return UserResponse(**{k: v for k, v in user_dict.items() if k != "password_hash"})

@app.get("/auth/users", response_model=list[UserResponse], tags=["Gestión de Usuarios"])
async def list_users(
    campus: Optional[str] = None,
    rol: Optional[str] = None,
    current_user = Depends(require_role(UserRole.ADMIN))
):
    """
    Listar todos los usuarios del sistema.
    Solo accesible para administradores.
    """
    try:
        query = "SELECT * FROM c WHERE STARTSWITH(c.id, 'user:')"
        params = []
        
        if campus:
            query += " AND c.campus = @campus"
            params.append({"name": "@campus", "value": campus})
        
        if rol:
            query += " AND c.rol = @rol"
            params.append({"name": "@rol", "value": rol})
        
        users = usuarios.query_items(query, params if params else None)
        return [UserResponse(**{k: v for k, v in u.items() if k != "password_hash"}) for u in users]
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al listar usuarios: {str(e)}")

@app.patch("/auth/users/{user_id}", response_model=UserResponse, tags=["Gestión de Usuarios"])
async def update_user(
    user_id: str,
    updates: UserUpdate,
    current_user = Depends(require_role(UserRole.ADMIN))
):
    """
    Actualizar información de un usuario.
    Solo accesible para administradores.
    """
    try:
        user_dict = usuarios.read_item(user_id, user_id)
        
        # Aplicar actualizaciones
        update_data = updates.dict(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                if key in ["rol", "campus"]:
                    user_dict[key] = value.value if hasattr(value, "value") else value
                else:
                    user_dict[key] = value
        
        usuarios.upsert_item(user_dict, user_id)
        
        # Auditoría
        log_audit(
            current_user.username,
            AuditAction.UPDATE_USER,
            user_id,
            f"Actualizó usuario: {update_data}"
        )
        
        return UserResponse(**{k: v for k, v in user_dict.items() if k != "password_hash"})
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar usuario: {str(e)}")

@app.get("/auth/audit-logs", tags=["Auditoría"])
async def get_audit_logs(
    usuario: Optional[str] = None,
    accion: Optional[str] = None,
    limit: int = 100,
    current_user = Depends(require_role(UserRole.ADMIN))
):
    """
    Obtener logs de auditoría del sistema.
    Solo accesible para administradores.
    """
    try:
        query = "SELECT * FROM c WHERE STARTSWITH(c.id, 'audit:') ORDER BY c.timestamp DESC"
        params = []
        
        if usuario:
            query = query.replace("WHERE", f"WHERE c.usuario = @usuario AND")
            params.append({"name": "@usuario", "value": usuario})
        
        if accion:
            if params:
                query = query.replace("ORDER BY", f"AND c.accion = @accion ORDER BY")
            else:
                query = query.replace("WHERE", f"WHERE c.accion = @accion AND")
            params.append({"name": "@accion", "value": accion})
        
        logs = auditoria.query_items(query, params if params else None, max_items=limit)
        return logs
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener logs: {str(e)}")

# ============================================
# ENDPOINTS DE VACUNACIÓN - TARJETA DE VACUNACIÓN
# ============================================

class VacunacionAplicacion(BaseModel):
    """Modelo para registrar una aplicación de vacuna"""
    id: Optional[str] = None
    matricula: str
    nombreEstudiante: Optional[str] = None
    campana: str
    vacuna: str
    dosis: int
    lote: Optional[str] = None
    aplicadoPor: Optional[str] = None
    fechaAplicacion: str  # ISO string
    observaciones: Optional[str] = None
    timestamp: Optional[str] = None

@app.post("/carnet/{matricula}/vacunacion")
async def guardar_aplicacion_vacuna(
    matricula: str, 
    aplicacion: VacunacionAplicacion,
    current_user: dict = Depends(get_current_user)
):
    """
    Guarda una aplicación de vacuna en el expediente del estudiante.
    Se almacena en el contenedor tarjeta_vacunacion con partition key /matricula
    Requiere autenticación JWT.
    """
    try:
        # Generar ID único si no viene
        if not aplicacion.id:
            aplicacion.id = f"vacuna_{matricula}_{int(datetime.now().timestamp() * 1000)}"
        
        # Generar timestamp si no viene
        if not aplicacion.timestamp:
            aplicacion.timestamp = datetime.now().isoformat()
        
        # Crear documento
        documento = {
            "id": aplicacion.id,
            "matricula": matricula,  # Partition key
            "nombreEstudiante": aplicacion.nombreEstudiante or "",
            "campana": aplicacion.campana,
            "vacuna": aplicacion.vacuna,
            "dosis": aplicacion.dosis,
            "lote": aplicacion.lote or "",
            "aplicadoPor": aplicacion.aplicadoPor or "",
            "fechaAplicacion": aplicacion.fechaAplicacion,
            "observaciones": aplicacion.observaciones or "",
            "timestamp": aplicacion.timestamp,
            "tipo": "aplicacion_vacuna"  # Para filtrar después
        }
        
        # Guardar en Cosmos DB
        result = tarjeta_vacunacion.create_item(documento)
        
        print(f"✅ Vacunación guardada: {aplicacion.id} - {matricula} - {aplicacion.vacuna}")
        
        return JSONResponse(
            status_code=201,
            content={
                "message": "Vacunación registrada exitosamente",
                "id": aplicacion.id,
                "matricula": matricula
            }
        )
    
    except CosmosHttpResponseError as e:
        print(f"❌ Error Cosmos al guardar vacunación: {e.status_code} - {e.message}")
        raise HTTPException(status_code=e.status_code or 500, detail=str(e.message))
    except Exception as e:
        print(f"❌ Error al guardar vacunación: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al guardar vacunación: {str(e)}")

@app.get("/carnet/{matricula}/vacunacion")
async def obtener_historial_vacunacion(
    matricula: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene el historial completo de vacunación de un estudiante.
    Retorna todas las aplicaciones ordenadas por fecha.
    Requiere autenticación JWT.
    """
    try:
        # Query para obtener todas las vacunaciones de este estudiante
        query = "SELECT * FROM c WHERE c.matricula = @matricula AND c.tipo = 'aplicacion_vacuna' ORDER BY c.fechaAplicacion DESC"
        params = [{"name": "@matricula", "value": matricula}]
        
        items = tarjeta_vacunacion.query_items(query, params)
        
        # Convertir a lista
        historial = list(items)
        
        print(f"📋 Historial de vacunación: {matricula} - {len(historial)} registros")
        
        return JSONResponse(
            status_code=200,
            content=historial
        )
    
    except CosmosHttpResponseError as e:
        print(f"❌ Error Cosmos al obtener historial: {e.status_code} - {e.message}")
        raise HTTPException(status_code=e.status_code or 500, detail=str(e.message))
    except Exception as e:
        print(f"❌ Error al obtener historial: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener historial: {str(e)}")

@app.get("/vacunacion/estadisticas")
async def obtener_estadisticas_vacunacion():
    """
    Obtiene estadísticas globales de vacunación.
    - Total de aplicaciones
    - Por vacuna
    - Por campaña
    """
    try:
        # Obtener todas las aplicaciones
        query = "SELECT * FROM c WHERE c.tipo = 'aplicacion_vacuna'"
        items = list(tarjeta_vacunacion.query_items(query, []))
        
        # Calcular estadísticas
        total_aplicaciones = len(items)
        
        # Por vacuna
        vacunas = {}
        campanas = {}
        estudiantes = set()
        
        for item in items:
            # Contar por vacuna
            vacuna = item.get("vacuna", "Desconocida")
            vacunas[vacuna] = vacunas.get(vacuna, 0) + 1
            
            # Contar por campaña
            campana = item.get("campana", "Sin campaña")
            campanas[campana] = campanas.get(campana, 0) + 1
            
            # Estudiantes únicos
            estudiantes.add(item.get("matricula"))
        
        return JSONResponse(
            status_code=200,
            content={
                "totalAplicaciones": total_aplicaciones,
                "estudiantesVacunados": len(estudiantes),
                "porVacuna": vacunas,
                "porCampana": campanas
            }
        )
    
    except Exception as e:
        print(f"❌ Error al obtener estadísticas: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener estadísticas: {str(e)}")

# ============================================
# SERVIR PANEL WEB DE ADMINISTRACIÓN
# ============================================
try:
    app.mount("/admin", StaticFiles(directory="admin_panel", html=True), name="admin")
    print("✅ Panel web admin disponible en /admin")
except Exception as e:
    print(f"⚠️  Panel web admin no disponible: {e}")

print("✅ Endpoints de autenticación registrados")
print(f"🔐 Roles disponibles: {[r.value for r in UserRole]}")
print(f"🏫 Campus disponibles: {[c.value for c in Campus]}")

# Force redeploy 2025-11-24 13:35
