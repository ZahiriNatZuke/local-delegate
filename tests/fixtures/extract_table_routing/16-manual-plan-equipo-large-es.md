# Manual del espacio de trabajo: Plan Básico y Plan Equipo

Este manual explica cómo se organiza un espacio de trabajo de Taller Nube, qué puede hacer cada tipo de usuario y qué límites tiene cada plan. Está pensado para quien administra el espacio; las personas que solo colaboran en un proyecto tienen bastante con la guía rápida.

## Cómo se organiza un espacio

Un espacio de trabajo reúne los proyectos de una misma organización. Cada proyecto tiene sus tableros, sus documentos y su carpeta de archivos. Los proyectos no comparten nada entre sí salvo las personas: un mismo usuario puede estar en varios proyectos con permisos distintos en cada uno.

Las tareas viven en tableros. Un tablero puede verse como lista, como columnas o como calendario, y la vista elegida se guarda por persona. Las columnas se pueden renombrar y reordenar; borrar una columna con tareas pide antes dónde moverlas.

Los documentos se editan en el navegador y guardan el historial de cambios. Se puede volver a cualquier versión anterior mientras el proyecto exista. Los archivos adjuntos a una tarea cuentan para el almacenamiento del proyecto, no para el de la persona que los subió.

## Tipos de usuario

- **Propietario**: crea el espacio, elige el plan y es el único que puede borrarlo. Puede haber más de uno.
- **Administrador**: crea proyectos, invita a personas y cambia permisos. No ve la facturación.
- **Usuario activo**: persona de la organización con cuenta propia. Puede crear tareas, documentos y tableros en los proyectos donde participa.
- **Usuario invitado**: persona de fuera (un cliente, un proveedor) que entra a uno o varios proyectos concretos. Ve y comenta, y puede editar solo las tareas que tiene asignadas.

Un usuario activo que pasa noventa días sin entrar se marca como inactivo y deja de contar para el límite hasta que vuelve a iniciar sesión. Los invitados no caducan, pero un administrador puede retirarles el acceso en cualquier momento.

## Límites de cada plan

Los límites se aplican por espacio de trabajo y se revisan cada trimestre. Cuando un espacio llega a un límite, lo que ya existe sigue funcionando; solo se impide crear más.

| Concepto | Plan Básico | Plan Equipo |
|---|---|---|
| Límite de usuarios activos | 10 | 75 |
| Límite de usuarios invitados | 3 | 20 |
| Límite de proyectos | 5 | 40 |
| Almacenamiento por proyecto | 2 GB | 25 GB |
| Retención de la papelera | 7 días | 45 días |
| Automatizaciones por tablero | 2 | 30 |

El soporte se atiende por correo en los dos planes. En el Plan Equipo hay además una sesión de puesta en marcha con una persona del equipo de producto durante el primer mes.

## La papelera

Todo lo que se borra va a la papelera del proyecto: tareas, documentos, archivos y tableros enteros. Desde allí se puede recuperar con un clic mientras dure la retención del plan. Pasado ese plazo se elimina de forma definitiva y deja de ocupar almacenamiento.

Vaciar la papelera a mano es posible, pero solo para administradores, y pide confirmación escribiendo el nombre del proyecto. No hay forma de recuperar lo que se vació a mano.

## Automatizaciones

Una automatización es una regla del tipo «cuando pase esto, haz aquello»: cuando una tarea llega a la columna «Hecho», avisa a quien la creó; cuando vence una fecha, sube la prioridad; cuando alguien adjunta un archivo, añade una etiqueta. Se configuran por tablero y se pueden pausar sin borrarlas.

Las automatizaciones se ejecutan en el orden en que se crearon. Si dos reglas se contradicen, gana la última. El registro de cada tablero muestra qué regla se ejecutó, cuándo y sobre qué tarea, durante treinta días.

## Permisos por proyecto

Cada proyecto tiene tres niveles: lectura, comentario y edición. El nivel se asigna por persona o por grupo. Un grupo es una lista de personas con nombre («Diseño», «Obra», «Proveedores»); cambiar el nivel del grupo cambia el de todas a la vez.

Los proyectos nuevos empiezan como privados: solo los ve quien fue añadido. Un administrador puede abrirlos a toda la organización, lo que da lectura a todos los usuarios activos sin añadirlos uno a uno. Los invitados nunca ven un proyecto al que no fueron añadidos de forma expresa.

## Exportar y cerrar

Un propietario puede exportar el espacio entero en un archivo comprimido: las tareas en CSV, los documentos en Markdown y los archivos tal como se subieron. La exportación se prepara en segundo plano y llega un aviso por correo cuando está lista; el enlace de descarga vale dos días.

Para cerrar un espacio hay que exportarlo o declarar que no se quiere copia. Tras el cierre, los datos se conservan treinta días por si fue un error y después se borran. Cambiar del Plan Equipo al Plan Básico no borra nada, pero impide crear proyectos o invitar personas mientras el espacio esté por encima de los límites del plan nuevo.

## Avisos

Cada persona elige qué avisos recibe y por dónde: dentro de la aplicación, por correo o en un resumen diario. Por defecto llegan las menciones, las tareas asignadas y los cambios de fecha de lo que uno tiene a su cargo. Los comentarios de una tarea solo avisan a quien la sigue.

El resumen diario sale a primera hora y agrupa lo ocurrido el día anterior por proyecto. Quien prefiera silencio puede pausar todos los avisos durante unas horas o hasta el lunes; las menciones marcadas como urgentes se entregan igual.

Un administrador puede fijar avisos obligatorios para un proyecto, por ejemplo el cierre de una fase. Esos avisos no se pueden desactivar mientras la persona siga en el proyecto.

## Preguntas frecuentes

**¿Puedo tener más de un espacio?** Sí. Cada espacio tiene su plan y sus límites, y una misma cuenta puede pertenecer a varios.

**¿Qué pasa con las tareas de alguien que se va?** Siguen en su sitio, sin persona asignada. El administrador recibe una lista para repartirlas.

**¿Los nombres de este manual son reales?** No. Taller Nube y sus planes son un ejemplo inventado para documentación.
