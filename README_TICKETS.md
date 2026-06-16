# API Comunicacion Institucional SASU

Modulo backend MVP para tickets institucionales SASU 2.6.0.

## Contenedores Cosmos

- `tickets`, configurable con `COSMOS_CONTAINER_TICKETS`.
- `ticket_messages`, configurable con `COSMOS_CONTAINER_TICKET_MESSAGES`.

Partition keys recomendadas:

- `tickets`: `/campus`
- `ticket_messages`: `/ticketId`

## Endpoints

### `POST /tickets`

Crea un ticket institucional. Requiere `tickets:create`.

Campos principales:

- `matricula`
- `nombrePaciente`
- `campus`
- `categoria`
- `prioridad`
- `titulo`
- `descripcionInicial`

El backend genera `id`, `ticketNumber`, `createdAtUtc`, `updatedAtUtc`, `createdBy` y estado `abierto`.

### `GET /tickets/my`

Devuelve tickets visibles para el usuario autenticado. Requiere `tickets:read`.

### `GET /tickets/{id}`

Devuelve detalle completo: ticket y mensajes.

### `POST /tickets/{id}/messages`

Agrega un mensaje al ticket. Requiere permiso de respuesta o participacion directa en el ticket.

### `GET /tickets/{id}/messages`

Devuelve el historial de mensajes del ticket.

### `PATCH /tickets/{id}/assign`

Asigna un profesional o area. Requiere `tickets:assign`.

### `PATCH /tickets/{id}/status`

Cambia el estado del ticket. Requiere `tickets:update_status`.

Estados validos:

- `abierto`
- `asignado`
- `en_atencion`
- `pendiente_paciente`
- `resuelto`
- `cerrado`

### `PATCH /tickets/{id}/appointment`

Registra atencion presencial o virtual y fecha UTC.

### `PATCH /tickets/{id}/videocall`

Registra URL externa `https://` para Meet, Teams u otro servicio institucional.

## Seguridad

- Todo endpoint requiere usuario autenticado.
- El acceso queda limitado al mismo campus salvo rol `admin`.
- No se modifica autenticacion, login, notas clinicas, SQLite, updater ni actividad reciente.
- No se almacenan secretos ni credenciales en este modulo.
