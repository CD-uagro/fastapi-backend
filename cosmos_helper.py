import os
import time
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from dotenv import load_dotenv

load_dotenv()

COSMOS_URL = os.environ["COSMOS_URL"]
COSMOS_KEY = os.environ["COSMOS_KEY"]


def get_cosmos_db_name():
    return os.environ.get("COSMOS_DB") or os.environ.get("COSMOS_DATABASE")


DB_NAME = get_cosmos_db_name()
if not DB_NAME:
    raise KeyError("COSMOS_DB")

class CosmosDBHelper:
    def __init__(self, container_name, partition_key):
        self.client = CosmosClient(COSMOS_URL, credential=COSMOS_KEY)
        self.database = self.client.get_database_client(DB_NAME)
        self.container = self.database.get_container_client(container_name)
        self.partition_key = partition_key

    def get_by_id(self, id_value):
        try:
            return self.container.read_item(item=id_value, partition_key=id_value)
        except CosmosHttpResponseError as e:
            raise CosmosHttpResponseError(status_code=e.status_code, message=e.message)
    
    def read_item(self, item_id, partition_key):
        """Lee un item por ID y partition key."""
        try:
            return self.container.read_item(item=item_id, partition_key=partition_key)
        except CosmosHttpResponseError as e:
            raise CosmosHttpResponseError(status_code=e.status_code, message=e.message)
    
    def create_item(self, item):
        """Crea un nuevo item en el contenedor."""
        try:
            return self.container.create_item(body=item)
        except CosmosHttpResponseError as e:
            raise CosmosHttpResponseError(status_code=e.status_code, message=e.message)

    def query_items(self, sql, params=None):
        try:
            return list(self.container.query_items(
                query=sql,
                parameters=params or [],
                enable_cross_partition_query=True
            ))
        except CosmosHttpResponseError as e:
            raise CosmosHttpResponseError(status_code=e.status_code, message=e.message)

    def upsert_item(self, item, partition_value):
        try:
            # Probar diferentes métodos según la versión del SDK
            try:
                # Método nuevo (azure-cosmos >= 4.0)
                result = self.container.upsert_item(body=item, partition_key=partition_value)
            except TypeError as te:
                if "partition_key" in str(te):
                    # Método viejo (azure-cosmos < 4.0) - pasar partition key en el item
                    pk_field = self.partition_key.lstrip('/')  # Remover '/' inicial
                    item[pk_field] = partition_value
                    result = self.container.upsert_item(item)
                else:
                    raise
            
            return result
        except CosmosHttpResponseError as e:
            # Retry para 429 (throttling)
            if e.status_code == 429:
                time.sleep(0.2)  # 200ms
                try:
                    # Retry una vez
                    try:
                        result = self.container.upsert_item(body=item, partition_key=partition_value)
                    except TypeError:
                        pk_field = self.partition_key.lstrip('/')
                        item[pk_field] = partition_value
                        result = self.container.upsert_item(item)
                    return result
                except CosmosHttpResponseError as retry_e:
                    raise CosmosHttpResponseError(status_code=retry_e.status_code, message=retry_e.message)
            
            # Idempotencia para 409 (conflict)
            if e.status_code == 409:
                # Devolver el documento actual
                try:
                    return self.get_by_id(item.get('id'))
                except:
                    raise CosmosHttpResponseError(status_code=e.status_code, message=e.message)
            
            raise CosmosHttpResponseError(status_code=e.status_code, message=e.message)


# Helpers específicos para citas (contenedor citas_ida)
def get_citas_container():
    """Retorna el contenedor de citas con inicialización perezosa"""
    try:
        client = CosmosClient(COSMOS_URL, credential=COSMOS_KEY)
        database = client.get_database_client(DB_NAME)
        container_name = os.environ.get("COSMOS_CONTAINER_CITAS", "cita_id")
        return database.get_container_client(container_name)
    except Exception as e:
        raise Exception(f"Error connecting to citas container: {str(e)}")

def get_citas_pk_path():
    """Detecta el partition key path del contenedor de citas"""
    pk_path = os.environ.get("COSMOS_PK_CITAS", "/id")
    if os.environ.get("DEBUG_CITAS", "false").lower() == "true":
        print(f"[DRY-RUN] PK path detectado: {pk_path}")
    return pk_path

def upsert_cita(doc):
    """Helper seguro para upsert de citas con lazy init"""
    import uuid
    from datetime import datetime
    
    # Lazy init: obtener contenedor aquí, no al inicio
    container = get_citas_container()
    pk_path = get_citas_pk_path()
    
    debug_enabled = os.environ.get("DEBUG_CITAS", "false").lower() == "true"
    if debug_enabled:
        print(f"[DRY-RUN] upsert_cita - container: cita_id, pk_path: {pk_path}")
        print(f"[DRY-RUN] payload keys: {list(doc.keys())}")
    
    # Autocompletar campos según PK
    if pk_path == "/id":
        if not doc.get("id"):
            doc["id"] = f"cita:{uuid.uuid4()}"
            if debug_enabled:
                print(f"[DRY-RUN] Auto-generado ID: {doc['id']}")
    elif pk_path == "/cita":
        if not doc.get("cita"):
            doc["cita"] = doc.get("matricula", "")
            if debug_enabled:
                print(f"[DRY-RUN] Auto-generado cita: {doc['cita']}")
    
    # Timestamps
    if not doc.get("createdAt"):
        doc["createdAt"] = datetime.utcnow().isoformat() + "Z"
    doc["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    
    if debug_enabled:
        print(f"[DRY-RUN] Justo antes de upsert - container_target = cita_id")
    
    try:
        if pk_path == "/id":
            partition_key = doc["id"]
        elif pk_path == "/cita":
            partition_key = doc["cita"]
        else:
            # Sin PK
            result = container.upsert_item(doc)
            if debug_enabled:
                print(f"[DRY-RUN] Upsert OK (sin PK): {result.get('id')}, _etag: {result.get('_etag')}")
            return result
        
        # Con PK
        try:
            result = container.upsert_item(body=doc, partition_key=partition_key)
        except TypeError:
            # SDK antiguo
            pk_field = pk_path.lstrip('/')
            doc[pk_field] = partition_key
            result = container.upsert_item(doc)
        
        if debug_enabled:
            print(f"[DRY-RUN] Upsert OK: status=created, id={result.get('id')}, _etag={result.get('_etag')}")
            # Verificación con read_item
            try:
                verify = container.read_item(item=result["id"], partition_key=partition_key)
                print(f"[DRY-RUN] Verificación read_item en cita_id: ✅ {verify.get('id')}")
            except:
                print(f"[DRY-RUN] Verificación read_item: ⚠️ No se pudo verificar")
        
        return result
        
    except CosmosHttpResponseError as e:
        if debug_enabled:
            print(f"[DRY-RUN] Error upsert: {e.status_code}")
        # Retry para 429 (throttling)
        if e.status_code == 429:
            time.sleep(0.2)
            return upsert_cita(doc)  # Retry una vez
        raise
