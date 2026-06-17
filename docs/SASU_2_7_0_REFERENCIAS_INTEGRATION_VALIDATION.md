# SASU 2.7.0 - Referencias y Contrarreferencias

## Validacion de integracion backend MVP

Fecha: 2026-06-17

Alcance:

- Solo `temp_backend`.
- No modifica Flutter Windows.
- No modifica Flutter Web.
- No modifica Node.
- No modifica Agenda Integrada.
- No modifica Tickets.
- No modifica JWT.
- No implica push, deploy ni release.

---

## 1. Objetivo de la validacion

Validar que el backend MVP de Referencias y Contrarreferencias funcione con la misma infraestructura Cosmos usada actualmente por:

- `appointments`
- `tickets`

La validacion se enfoca en:

- creacion de referencia
- lectura por ID
- listado con filtros
- actualizacion de estado
- contrarreferencia
- serializacion
- fechas
- enums
- `statusHistory`
- auditoria

---

## 2. Archivos revisados

```text
cosmos_helper.py
appointment_repository.py
ticket_repository.py
referral_repository.py
referral_models.py
referral_routes.py
tests/test_referral_models.py
tests/test_referral_routes.py
```

---

## 3. Comparacion con appointments

`appointments` usa:

```text
COSMOS_CONTAINER_APPOINTMENTS=appointments
COSMOS_PK_APPOINTMENTS=/student/matricula
CosmosDBHelper.create_item()
CosmosDBHelper.query_items()
CosmosDBHelper.upsert_item()
```

`referrals` usa:

```text
COSMOS_CONTAINER_REFERRALS=referrals
COSMOS_PK_REFERRALS=/student/matricula
CosmosDBHelper.create_item()
CosmosDBHelper.query_items()
CosmosDBHelper.upsert_item()
```

Resultado:

```text
COMPATIBLE
```

La estrategia de persistencia de referencias replica el patron de Agenda Integrada: contenedor configurable, partition key por matricula y queries por filtros.

---

## 4. Comparacion con tickets

`tickets` usa:

- `create_item()` para crear documento principal
- `query_items()` para obtener por ID y filtrar
- `upsert_item()` para actualizar documento
- historial embebido en el documento
- auditoria basica de usuario y rol

`referrals` usa:

- `create_item()` para crear referencia
- `query_items()` para obtener por ID y filtrar
- `upsert_item()` para actualizar estado y contrarreferencia
- `statusHistory` embebido
- `createdBy`, `createdByRole`, `updatedBy`, `updatedByRole`

Resultado:

```text
COMPATIBLE
```

No se detecta necesidad de modificar Tickets.

---

## 5. Contenedor y partition key

Contenedor:

```text
referrals
```

Partition key:

```text
/student/matricula
```

Variables soportadas:

```text
COSMOS_CONTAINER_REFERRALS=referrals
COSMOS_PK_REFERRALS=/student/matricula
```

Si no se definen, el codigo usa esos valores como default.

Validacion local con helper compatible:

```text
referral repository integration validation OK
partition values used: ['15662', '15662']
```

Esto confirma que `update_referral()` calcula el partition value desde:

```text
referral.student.matricula
```

---

## 6. Validacion de operaciones

### create referral

Ruta:

```text
POST /referrals
```

Persistencia:

```text
CosmosReferralRepository.create_referral()
-> CosmosDBHelper.create_item()
```

Validado:

- asigna `id`
- asigna `type = referral`
- asigna `schemaVersion = 1`
- conserva `student.matricula`
- conserva `origin`
- conserva `destination`
- crea `createdAt`
- crea `updatedAt`
- crea `createdBy`
- crea `createdByRole`
- crea `statusHistory`

### get referral

Ruta:

```text
GET /referrals/{referral_id}
```

Persistencia:

```text
CosmosReferralRepository.get_referral()
-> SELECT * FROM c WHERE c.id = @id AND c.type = 'referral'
```

Validado:

- obtiene documento por `id`
- devuelve `404` si no existe
- aplica permiso por area/rol en ruta

Nota:

- Esta consulta es cross-partition, igual que el patron actual usado por Tickets y Appointments para lookup por ID.

### list referrals

Ruta:

```text
GET /referrals
```

Filtros:

```text
status
priority
origin_area
destination_area
matricula
student_name
```

Validado:

- filtra por estado
- filtra por prioridad
- filtra por area origen
- filtra por area destino
- filtra por matricula
- permite busqueda por nombre
- aplica scope por area cuando no es administrador

### update status

Ruta:

```text
PATCH /referrals/{referral_id}/status
```

Persistencia:

```text
CosmosReferralRepository.update_referral()
-> CosmosDBHelper.upsert_item(item, student.matricula)
```

Validado:

- valida transicion
- valida permiso por rol/area
- actualiza `status`
- actualiza `updatedAt`
- actualiza `updatedBy`
- actualiza `updatedByRole`
- agrega evento a `statusHistory`
- escribe timestamp especifico:
  - `receivedAt`
  - `acceptedAt`
  - `scheduledAt`
  - `attendedAt`
  - `closedAt`
  - `cancelledAt`
- guarda `appointmentId` si pasa a `scheduled`
- guarda `cancellationReason` si pasa a `cancelled`

### counter referral

Ruta:

```text
POST /referrals/{referral_id}/counter-referral
```

Persistencia:

```text
counterReferral embebida dentro del documento Referral
```

Validado:

- guarda `responseArea`
- guarda `responseUserId`
- guarda `responseUserName`
- guarda `responseRole`
- guarda `summary`
- guarda `recommendations`
- guarda `followUpRequired`
- guarda `followUpArea`
- guarda `nextSuggestedAction`
- guarda `createdAt`
- agrega evento a `statusHistory`
- bloquea si la referencia esta `closed`
- bloquea si la referencia esta `cancelled`

---

## 7. Serializacion

Modelos Pydantic:

```text
Referral
ReferralCreate
ReferralUpdateStatus
CounterReferralCreate
CounterReferral
StatusHistoryItem
```

Configuracion:

```text
use_enum_values = True
```

Resultado:

- Los enums se serializan como strings.
- Los documentos quedan compatibles con JSON de Cosmos.
- Las respuestas FastAPI exponen valores legibles.

Ejemplos:

```text
status = "sent"
priority = "media"
origin.area = "medico"
destination.area = "psicologia"
```

---

## 8. Fechas

Formato usado:

```text
datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
```

Ejemplo:

```text
2026-06-17T18:00:00.000000Z
```

Campos revisados:

- `createdAt`
- `updatedAt`
- `receivedAt`
- `acceptedAt`
- `scheduledAt`
- `attendedAt`
- `closedAt`
- `cancelledAt`
- `counterReferral.createdAt`
- `statusHistory[].at`

Resultado:

```text
COMPATIBLE
```

Nota:

- El formato es consistente con tickets.
- Agenda usa campos snake_case (`updated_at`) en su modelo actual; referencias usa camelCase segun diseno documental.

---

## 9. Enums

Estados:

```text
draft
sent
received
accepted
scheduled
attended
closed
cancelled
```

Prioridades:

```text
baja
media
alta
urgente
```

Areas:

```text
medico
psicologia
nutricion
odontologia
atencion_estudiantil
```

Resultado:

```text
COMPATIBLE
```

Los valores coinciden con los documentos funcional y tecnico.

---

## 10. statusHistory

Cada evento guarda:

```text
previousStatus
status
at
byUserId
byUserName
byRole
area
note
appointmentId
metadata
```

Validado:

- creacion inicial agrega evento
- cambio de estado agrega evento
- contrarreferencia agrega evento con metadata
- no se borra historial anterior

Resultado:

```text
COMPATIBLE
```

---

## 11. Auditoria

Campos guardados:

```text
createdBy
createdByRole
updatedBy
updatedByRole
createdAt
updatedAt
statusHistory
```

Resultado:

```text
COMPATIBLE PARA MVP
```

Pendiente futuro:

- Si se requiere nombre completo institucional, el backend actual solo tiene `TokenData.username`; no expone `nombre_completo` en el token.
- Para MVP se usa `username` como `userName`.

---

## 12. Problemas detectados

No se detectaron incompatibilidades que requieran cambio de codigo en esta etapa.

Observaciones tecnicas:

1. `get_referral()` es cross-partition por ID.
2. La bandeja por area destino es cross-partition.
3. La busqueda por nombre usa `LOWER()` y `CONTAINS()`, lo que puede elevar RU si hay volumen alto.
4. `CosmosDBHelper.query_items()` no soporta partition key explicita, igual que el patron actual de tickets/appointments.

Estas observaciones no bloquean el MVP.

---

## 13. Riesgos y mitigaciones

### RU por bandeja de area

Riesgo:

- El listado por `destination.area` no coincide con la partition key.

Mitigacion:

- Filtrar por estado y area.
- Agregar paginacion antes de crecimiento productivo.
- Mantener polling moderado.

### Lookup por ID

Riesgo:

- Consulta cross-partition.

Mitigacion:

- Aceptable para MVP.
- En fase posterior, usar `matricula + referralId` cuando el frontend tenga ambos datos.

### Busqueda por nombre

Riesgo:

- `LOWER()` puede disminuir aprovechamiento de indice.

Mitigacion:

- Mantener para MVP.
- Agregar campo normalizado `student.nombreSearch` si crece el volumen.

---

## 14. Pruebas ejecutadas

Validacion local del repositorio con helper compatible:

```text
referral repository integration validation OK
partition values used: ['15662', '15662']
```

Suite completa:

```text
python -m unittest discover
Ran 37 tests
OK
```

---

## 15. Dictamen

```text
APTO PARA SIGUIENTE ETAPA BACKEND CONTROLADA
```

El backend MVP de referencias es compatible con la infraestructura Cosmos actual usada por appointments y tickets.

No se requieren cambios de codigo en esta etapa.
