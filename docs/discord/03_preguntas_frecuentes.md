--- MENSAJE 1 ---
# ❓ ¿Es seguro usar Farmadex?

Farmadex no toca el juego: no lee ni escribe su memoria, no modifica sus ficheros, no inyecta nada, no pulsa teclas por ti y no entra en tu cuenta. Lo único que hace es mirar tu pantalla (por ejemplo, para leer las recompensas de una reliquia) y el registro que el propio juego escribe (`EE.log`), igual que llevan años haciendo otras herramientas conocidas de la comunidad, como WFInfo o AlecaFrame.

Dicho esto, hay que ser honestos: **Digital Extremes no aprueba ni respalda ningún programa de terceros**, lo diga quien lo diga. Su postura oficial es que usarlos es bajo tu propia responsabilidad. Creemos que Farmadex se queda lejos de lo que esa política persigue, pero nadie —ni nosotros, ni tú, ni DE— puede prometerte que no exista ningún riesgo. La decisión de usarlo es tuya.

Todo el detalle, con capturas: https://github.com/angelsanchez97/farmadex/blob/main/docs/SEGURIDAD.md

--- MENSAJE 2 ---
# ❓ ¿Por qué Windows dice que puede ser peligroso?

Es SmartScreen, y sale con cualquier programa nuevo que no lleve una firma digital de pago. Farmadex no la lleva porque es gratis y lo hace una sola persona; ese certificado cuesta bastante dinero cada año.

El aviso no significa que tenga un virus, solo que Windows todavía no lo conoce. Para seguir: pulsa **"Más información"** y luego **"Ejecutar de todas formas"**.

Si quieres estar tranquilo, descárgalo solo desde la página oficial de versiones y comprueba el fichero con `SHA256SUMS.txt` (lo explicamos con detalle en el canal de bienvenida).

--- MENSAJE 3 ---
# ❓ No reconoce un objeto / me sale "Sin identificar"

Puede pasar por varias razones: el objeto es muy nuevo y los datos todavía no lo traen, el juego lo pintó tapado por algo en pantalla, o simplemente hay un caso que no contemplamos.

Cuando Farmadex no está seguro de lo que ha leído, prefiere decir "Sin identificar" antes que arriesgarse a decirte algo que no es. Si te pasa con algo que debería reconocer, cuéntanoslo en el canal de soporte o abre un issue en GitHub, diciendo qué objeto era y en qué pantalla lo viste — así podemos revisarlo.

--- MENSAJE 4 ---
# ❓ Los atajos de teclado no funcionan

Lo más probable es que otro programa ya esté usando esa combinación (el propio Windows, OBS, otro overlay...). Farmadex avisa cuando no consigue quedarse con un atajo, pero es fácil que se pase por alto.

La solución: ve a **Ajustes > Atajos** y cámbialo por otra combinación que tengas libre. No hace falta reiniciar nada, se aplica al momento.

--- MENSAJE 5 ---
# ❓ Cómo mandar un informe si algo falla

Si algo no funciona como debería (sobre todo con las reliquias), ve a **Ajustes > Reliquias > Guardar informe para enviar**. Farmadex genera un archivo con lo necesario para diagnosticar el problema —sin nada de tu cuenta del juego— y te dice dónde lo ha dejado.

Pásanoslo por aquí, en el canal de soporte, o adjúntalo a un issue en GitHub, contando qué estabas haciendo cuando pasó.

--- MENSAJE 6 ---
# ❓ ¿Gasta mucho el PC mientras juego?

Farmadex está pensado para vivir de fondo mientras juegas, sin robarle recursos a Warframe. Solo mira la pantalla cuando hace falta (al abrir una reliquia, al pasar el ratón por un objeto...) y se queda tranquilo el resto del tiempo.

Si notas que tu equipo va justo, en **Ajustes > Avanzado** puedes elegir un modo de lectura de pantalla más ligero. Por defecto ya viene en automático, así que se adapta solo según lo cargada que vaya tu CPU en cada momento.

--- MENSAJE 7 ---
# ❓ ¿En qué idiomas está disponible?

Español, inglés, francés, alemán y portugués, con la terminología oficial del juego en cada uno (nombres de misiones, reliquias, etc.). Se cambia al vuelo desde **Ajustes**, sin reiniciar el programa.

Por defecto Farmadex intenta usar el idioma de Windows si está entre esos cinco, y si no, se queda en español.

--- MENSAJE 8 ---
# ❓ ¿Cómo se actualiza?

Solo. Farmadex descarga la versión nueva por detrás mientras juegas y la instala cuando cierras el programa (nunca en mitad de una partida). La versión anterior se cierra del todo, sin dejar restos.

Si prefieres controlarlo tú, puedes desactivar las actualizaciones automáticas en Ajustes; en ese caso solo te avisará con un enlace para bajarla a mano. Y si usas la versión portable (el `.zip`), la actualización siempre es manual: baja la nueva desde https://github.com/angelsanchez97/farmadex/releases/latest
