# Recuperación de contraseña por correo

Acceso público para todos los roles: `/recuperar`. El panel administrativo incluye un enlace en «Olvidé mi usuario o contraseña». Las aplicaciones instaladas pueden utilizar esa misma dirección desde su navegador, sin reinstalación.

## Activación en Render

1. Crear una cuenta en Resend.
2. Añadir y verificar un dominio que el propietario pueda administrar en DNS. No utilizar una dirección UAGro como remitente sin autorización del dominio.
3. Crear una clave de API con permiso de envío para ese dominio.
4. En Render, servicio `fastapi-backend-o7ks`, sección Environment, guardar:

   ```text
   RESEND_API_KEY=<clave guardada únicamente en Render>
   PASSWORD_RESET_FROM=SASU <acceso@tu-dominio-verificado>
   PASSWORD_RESET_BASE_URL=https://fastapi-backend-o7ks.onrender.com
   PASSWORD_RESET_ENABLED=true
   ```

5. Guardar la configuración y permitir el reinicio del servicio.
6. Probar con una cuenta autorizada cuyo correo registrado sea accesible. Confirmar recepción, cambio de contraseña, acceso con la nueva contraseña y rechazo del enlace al reutilizarlo. Revisar en Resend el estado de entrega si el correo no llega.

Sin configuración completa, las rutas nuevas permanecen deshabilitadas. El formulario lo explica y no promete un envío. El inicio de sesión existente continúa funcionando. Para desactivar la recuperación sin revertir código, establecer `PASSWORD_RESET_ENABLED=false`.

## Comportamiento

- El usuario introduce usuario, institución y correo registrado. La respuesta no confirma si la cuenta existe.
- Solo se envía al correo que ya figura en una cuenta activa; no se admite elegir un destinatario diferente.
- El enlace contiene un secreto aleatorio de 256 bits, se almacena únicamente su SHA-256 y vence a los 15 minutos.
- El secreto viaja en el fragmento del enlace, que no llega en la petición HTTP del navegador. La página lo retira de la dirección visible y no carga recursos externos.
- El consumo usa la condición ETag de Cosmos: dos intentos concurrentes no pueden aplicar dos restablecimientos sobre la misma versión.
- Al confirmar, se conserva la cuenta y se actualizan contraseña y bloqueo. No se inicia sesión automáticamente. Se registra una acción de auditoría sin contraseña ni token.
- Cambiar correo, desactivar la cuenta o cambiar manualmente la contraseña invalida el enlace.
- No se modifican las cuentas al solicitar un enlace, salvo añadir metadatos de recuperación. No se crean contenedores ni se ejecutan migraciones.
- Los límites se guardan en el contenedor `usuarios` con IDs `reset-rate:`; las consultas existentes de usuarios seleccionan IDs `user:` y excluyen estos registros. Se permite una nueva emisión por cuenta cada 60 segundos, hasta diez solicitudes por IP cada quince minutos y cien globales. Confirmación: veinte intentos por IP cada quince minutos.
- Las sesiones de otros dispositivos mantienen el comportamiento existente y pueden durar hasta el vencimiento de su JWT. Esta entrega no cambia el mecanismo de sesiones de las aplicaciones instaladas.
- El envío utiliza tareas en segundo plano del proceso y la API HTTPS de Resend, con un tiempo máximo de diez segundos. Si el proceso se interrumpe o el proveedor falla, el correo puede no llegar; el usuario puede solicitar otro enlace. Los logs registran el tipo de fallo, sin token, correo ni clave.

## Pruebas

```text
python -X utf8 -B -m unittest discover -s tests -p "test_*.py" -q
node --test tests/access.test.js
python -X utf8 -B tests/browser_access.py
python -X utf8 -B tests/browser_recovery.py
```

Las pruebas no envían correos reales ni escriben en la base de producción. Para el navegador se utiliza Chrome instalado o la ruta `SASU_BROWSER_PATH`.

Referencia: [OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html), [API de envío de Resend](https://resend.com/docs/api-reference/emails/send-email) y [verificación de dominios de Resend](https://resend.com/docs/dashboard/domains/introduction).
