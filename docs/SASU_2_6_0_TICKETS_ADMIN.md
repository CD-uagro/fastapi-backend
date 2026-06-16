# SASU 2.6.0 - Administracion de tickets

## Arquitectura

El modulo de tickets vive en el backend FastAPI `fastapi-backend-o7ks` y esta montado bajo `/tickets`.

El flujo alumno se mantiene separado:

- `POST /tickets` permite que el alumno cree tickets usando el JWT del Carnet Digital.
- `GET /tickets/my` permite que el alumno consulte solo sus propios tickets.
- El adaptador JWT alumno sigue usando `STUDENT_JWT_SECRET`.

El flujo operador/admin usa el mismo router, pero solo acepta usuarios internos SASU. La autorizacion se basa en roles y permisos internos, no en el campus del usuario.

## Campus y unidades

Durante la configuracion inicial varios usuarios internos de distintas unidades quedaron registrados con `campus = cres-llano-largo`. Por esta razon:

- `campus` no restringe permisos de usuarios internos.
- `campus` se usa solo como filtro de consulta.
- La restriccion fuerte para alumnos sigue siendo la matricula del token.
- El diseno conserva el campo `campus` para una futura normalizacion del catalogo de usuarios.

## Persistencia Cosmos DB

Los tickets se guardan en el contenedor configurado por `COSMOS_CONTAINER_TICKETS`.

Los mensajes y seguimientos se guardan en el contenedor existente `COSMOS_CONTAINER_TICKET_MESSAGES`, particionado por `ticketId`.

Los seguimientos no se embeben en el ticket. Se guardan como documentos independientes con:

```json
{
  "id": "ticketmsg:...",
  "ticketId": "ticket:...",
  "ticket_id": "ticket:...",
  "author": "psico1",
  "role": "psicologia",
  "message": "Seguimiento interno",
  "visibility": "internal",
  "created_at": "2026-06-16T00:00:00.000000Z",
  "metadata": {
    "messageType": "followup",
    "visibility": "internal"
  }
}
```

## Autenticacion

Todos los endpoints administrativos requieren `Authorization: Bearer <jwt interno SASU>`.

Los JWT de alumno no pueden usar:

- `GET /tickets`
- `GET /tickets/{ticket_id}`
- `PATCH /tickets/{ticket_id}/status`
- `POST /tickets/{ticket_id}/followups`

## Endpoints

### GET /tickets

Lista tickets para usuarios internos SASU.

Filtros opcionales:

- `status`
- `category`
- `priority`
- `campus`
- `unidad_academica`
- `preparatoria`
- `student_id`
- `matricula`

Ejemplo:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://fastapi-backend-o7ks.onrender.com/tickets?status=abierto&category=psicologia"
```

### GET /tickets/{ticket_id}

Devuelve detalle completo para usuarios internos:

- ticket
- messages
- followups

Ejemplo:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://fastapi-backend-o7ks.onrender.com/tickets/ticket:abc"
```

### PATCH /tickets/{ticket_id}/status

Actualiza estado y guarda historial.

Estados administrativos:

- `abierto`
- `en_revision`
- `en_proceso`
- `resuelto`
- `cerrado`
- `cancelado`

Estados legacy retenidos por compatibilidad:

- `asignado`
- `en_atencion`
- `pendiente_paciente`

Ejemplo:

```bash
curl -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"estado":"en_revision"}' \
  "https://fastapi-backend-o7ks.onrender.com/tickets/ticket:abc/status"
```

Cada cambio agrega una entrada en `statusHistory`:

```json
{
  "previousStatus": "abierto",
  "newStatus": "en_revision",
  "changedBy": "psico1",
  "changedByRole": "psicologia",
  "changedAtUtc": "2026-06-16T00:00:00.000000Z"
}
```

### POST /tickets/{ticket_id}/followups

Agrega un seguimiento interno.

`visibility` acepta:

- `internal`
- `student`

Ejemplo:

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Se canaliza a psicologia.","visibility":"internal"}' \
  "https://fastapi-backend-o7ks.onrender.com/tickets/ticket:abc/followups"
```

## Errores esperados

- `401`: token ausente o invalido.
- `403`: usuario sin permiso o JWT alumno intentando usar endpoint admin.
- `404`: ticket inexistente.
- `422`: estado invalido, seguimiento vacio o payload invalido.

## Compatibilidad

No se modifica el contrato alumno existente:

- `POST /tickets`
- `GET /tickets/my`
- validacion con `STUDENT_JWT_SECRET`
- filtro por matricula para alumnos

El siguiente paso natural es crear la UI operador/admin para consumir estos endpoints.
