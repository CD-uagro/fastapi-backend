# SASU 2.7.0 - Referencias y Contrarreferencias

## Validacion Cosmos DB para MVP backend

Fecha: 2026-06-17

Alcance:

- Solo `temp_backend`.
- No modifica Flutter.
- No modifica Node.
- No modifica Agenda Integrada.
- No modifica Tickets.
- No modifica JWT.
- No implica push, deploy ni release.

---

## 1. Fuente revisada

Archivos inspeccionados:

```text
cosmos_helper.py
ticket_repository.py
appointment_repository.py
referral_repository.py
referral_routes.py
referral_models.py
```

Patrones existentes usados como referencia:

- Tickets:
  - `CosmosTicketRepository`
  - contenedor `tickets`
  - queries cross-partition por `id`, filtros y campus
  - `upsert_item` con partition value explicito
- Agenda Integrada:
  - `CosmosAppointmentRepository`
  - contenedor `appointments`
  - partition key configurable por `COSMOS_PK_APPOINTMENTS`
  - default `/student/matricula`
  - queries por `id`, matricula, area, estado y prioridad

---

## 2. Contenedor Cosmos requerido

Contenedor requerido:

```text
referrals
```

Variable opcional soportada por el codigo:

```text
COSMOS_CONTAINER_REFERRALS
```

Valor recomendado:

```text
COSMOS_CONTAINER_REFERRALS=referrals
```

Si la variable no existe, el repositorio usa `referrals` como valor por defecto.

---

## 3. Partition key esperada

Partition key esperada:

```text
/student/matricula
```

Variable opcional soportada por el codigo:

```text
COSMOS_PK_REFERRALS
```

Valor recomendado:

```text
COSMOS_PK_REFERRALS=/student/matricula
```

Si la variable no existe, el repositorio usa `/student/matricula` como valor por defecto.

Compatibilidad:

- La estructura del modelo `Referral` guarda la matricula en:

```text
student.matricula
```

- `create_referral()` crea el documento completo con `student.matricula`.
- `update_referral()` calcula el partition value desde `referral.student.matricula`.
- Esto es compatible con un contenedor Cosmos configurado con `/student/matricula`.

---

## 4. Compatibilidad con CosmosDBHelper actual

`CosmosDBHelper` expone:

```text
create_item(item)
query_items(sql, params)
upsert_item(item, partition_value)
read_item(item_id, partition_key)
```

El repositorio de referencias usa:

```text
create_item()
query_items()
upsert_item()
```

No usa `get_by_id()`, porque ese helper asume partition key igual al `id`, lo cual no aplica para `referrals`.

Conclusion:

- El patron de `referral_repository.py` es compatible con el helper actual.
- Sigue el mismo patron de `appointment_repository.py`.
- No requiere modificar `cosmos_helper.py` para el MVP.

---

## 5. Consultas revisadas

### Por ID

Codigo:

```sql
SELECT * FROM c WHERE c.id = @id AND c.type = 'referral'
```

Caracteristicas:

- Consulta cross-partition.
- Compatible con el patron actual de tickets y appointments.
- Adecuada para MVP.

Riesgo:

- Mayor consumo de RU si el contenedor crece mucho.

Mitigacion futura:

- Exponer rutas que incluyan matricula cuando sea posible.
- Guardar indice auxiliar si el volumen crece.
- Agregar metodo `get_referral_by_student(referral_id, matricula)` para lecturas con partition key.

### Por matricula

Codigo:

```sql
SELECT * FROM c
WHERE c.type = 'referral'
AND c.student.matricula = @matricula
ORDER BY c.createdAt DESC
```

Caracteristicas:

- Logicamente alineada con la partition key.
- `CosmosDBHelper.query_items()` habilita cross-partition de forma global, por lo que funciona aunque no pasa partition key explicita.

Riesgo:

- No aprovecha al maximo la optimizacion de particion porque el helper no acepta partition key en queries.

Mitigacion futura:

- Agregar metodo opcional en helper para query por partition key sin romper tickets ni appointments.

### Por area destino

Codigo:

```sql
SELECT * FROM c
WHERE c.type = 'referral'
AND c.destination.area = @destination_area
ORDER BY c.updatedAt DESC
```

Uso:

- Bandeja de referencias.
- Notificaciones internas por area.

Caracteristicas:

- Cross-partition por diseno.
- Necesaria porque la partition key es matricula, no area.

Riesgo:

- Puede consumir mas RU cuando haya muchas referencias.

Mitigacion:

- Mantener filtros por estado y area.
- Paginacion en fase de UI.
- Si el volumen crece, evaluar materializacion de bandejas por area o contenedor auxiliar.

### Pendientes

Codigo:

```sql
SELECT * FROM c
WHERE c.type = 'referral'
AND ARRAY_CONTAINS(@pending_statuses, c.status)
AND c.destination.area = @area
ORDER BY c.updatedAt DESC
```

Estados pendientes:

```text
sent
received
accepted
```

Uso:

- Notificaciones internas tipo Messenger.
- Bandeja pendiente por area.

Compatibilidad:

- Sigue el patron usado en appointments para listas activas.

Riesgo:

- Polling frecuente podria incrementar RU.

Mitigacion:

- Intervalo recomendado: 60 a 120 segundos.
- Limitar resultados en una fase posterior si el volumen crece.
- Evitar polling cuando el modulo de referencias este activo.

---

## 6. Indices sugeridos

Con la politica de indexacion por defecto de Cosmos, estas rutas quedan normalmente cubiertas.

Rutas relevantes:

```text
/type
/id
/status
/priority
/student/matricula
/student/nombre
/origin/area
/destination/area
/appointmentId
/createdAt
/updatedAt
/counterReferral/createdAt
```

Consultas que dependen de ordenamiento:

```text
ORDER BY c.updatedAt DESC
ORDER BY c.createdAt DESC
```

Recomendacion:

- Mantener indexacion por defecto para MVP.
- Si Cosmos reporta errores de ORDER BY o alto RU, revisar politica de indexing para `createdAt` y `updatedAt`.
- Si se agrega paginacion, mantener el orden por `updatedAt` en bandejas.

---

## 7. Relacion con appointments

La relacion funcional se mantiene por campos, sin modificar Agenda en esta etapa.

Campos esperados:

```text
referrals.appointmentId
appointments.referralId
appointments.sourceType = "referral"
appointments.sourceId = referrals.id
```

Estado actual:

- El backend de referencias ya permite guardar `appointmentId` al pasar a estado `scheduled`.
- No se modifico `appointment_repository.py`.
- No se modificaron endpoints de Agenda.

Pendiente para fase de integracion Agenda:

- Crear cita desde referencia aceptada.
- Escribir `referralId` o `sourceId` en appointment.
- Bloquear duplicados activos.

---

## 8. Riesgos RU / cross-partition

### Riesgo 1: lectura por id cross-partition

Impacto:

- Bajo en MVP.
- Medio si el contenedor crece significativamente.

Mitigacion futura:

- Lectura por `id + matricula`.
- Mantener `student.matricula` disponible en contexto UI.

### Riesgo 2: bandeja por area destino

Impacto:

- Medio, porque la partition key no es area.

Justificacion:

- La partition key por matricula favorece Expediente, que es el eje historico del estudiante.
- Area destino como partition key dificultaria timeline por estudiante.

Mitigacion:

- filtros por estado
- polling moderado
- paginacion futura
- posible contenedor auxiliar si crece la operacion

### Riesgo 3: helper sin query por partition key

Impacto:

- Bajo para MVP.

Mitigacion:

- No modificar helper compartido en esta fase para evitar efectos colaterales en Tickets o Agenda.
- Evaluar extension compatible en una fase posterior:

```text
query_items(sql, params=None, partition_key=None)
```

---

## 9. Validacion de compatibilidad

Compatibilidad confirmada con:

- `CosmosDBHelper`
- patron de `CosmosAppointmentRepository`
- patron de `CosmosTicketRepository`
- modelo `Referral.student.matricula`
- partition key `/student/matricula`
- variables configurables por entorno

No se detecto ajuste obligatorio en `referral_repository.py` para el MVP.

---

## 10. Variables requeridas para produccion

Requeridas ya existentes para Cosmos:

```text
COSMOS_URL o COSMOS_ENDPOINT
COSMOS_KEY
COSMOS_DB o COSMOS_DATABASE
```

Recomendadas para referencias:

```text
COSMOS_CONTAINER_REFERRALS=referrals
COSMOS_PK_REFERRALS=/student/matricula
```

Si no se definen, el codigo usa los defaults anteriores.

---

## 11. Resultado

Dictamen:

```text
COMPATIBLE PARA MVP BACKEND
```

Condiciones:

- Crear contenedor `referrals` en Cosmos con partition key `/student/matricula`.
- Mantener indexacion por defecto.
- Monitorear RU en bandeja por area y polling de pendientes.
- No desplegar hasta validar variables y contenedor en Render.

No se requiere cambio adicional de codigo para esta etapa.
