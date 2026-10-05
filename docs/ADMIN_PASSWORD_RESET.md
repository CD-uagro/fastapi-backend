# Restablecimiento asistido para cuentas de la app SASU

En el panel, abre **Usuarios** y pulsa **Restablecer contraseña** en la fila de la persona. Comprueba su nombre, usuario, campus y correo; verifica su identidad por un medio conocido. Escribe una nueva contraseña y su confirmación, marca la verificación y guarda. Comunica la contraseña por un medio privado. La persona inicia sesión en su app instalada con su usuario y campus habituales.

No requiere Resend, dominio ni cambios en las apps instaladas. Solo un administrador autenticado puede ejecutar `POST /auth/users/{user_id}/reset-password`. La cuenta debe estar activa. El servidor valida la contraseña y guarda únicamente su hash, desbloquea los intentos fallidos e invalida los enlaces de recuperación pendientes. Conserva los demás campos de la cuenta. Una actualización concurrente cancela el cambio y pide reintentar.

Auditoría registra quién restableció la cuenta y el usuario afectado, sin contraseña ni hash. La casilla documenta la confirmación del administrador; la verificación de identidad se realiza fuera del sistema. Este cambio conserva el comportamiento actual de las sesiones: los tokens emitidos antes del restablecimiento siguen vigentes hasta su vencimiento habitual. No impone un cambio obligatorio de contraseña al entrar en las apps existentes.
