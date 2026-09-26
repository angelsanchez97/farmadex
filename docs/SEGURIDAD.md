# ¿Es seguro Farmadex?

Esta página explica, sin tecnicismos, por qué Windows avisa al instalar Farmadex,
cómo asegurarte de que tienes la versión buena y qué hace y qué no hace el programa
en tu ordenador. Lo mismo está resumido dentro de la app, en la bienvenida y en
Ajustes > Acerca de Farmadex.

## Por qué Windows avisa al instalarlo

Al abrir el instalador, Windows puede enseñar un aviso azul que dice
«Windows protegió tu PC» o que no reconoce la aplicación. Es **SmartScreen**, y
sale con los programas nuevos que no llevan una **firma digital de pago**.

Farmadex todavía no la lleva: es gratis, lo hace una sola persona y ese
certificado cuesta bastante dinero cada año. El aviso **no quiere decir que tenga
un virus**, solo que Windows aún no conoce el programa. Para seguir:

1. Pulsa **«Más información»**.
2. Pulsa **«Ejecutar de todas formas»**.

El instalador no pide permisos de administrador: se instala solo para tu usuario.

## De dónde descargarlo

Descárgalo **solo** de la página de versiones del proyecto en GitHub:

**<https://github.com/angelsanchez97/farmadex/releases>**

Si te lo pasan por otro sitio (un Discord, una web de descargas, un amigo), no
puedes saber si alguien lo ha cambiado por el camino. Todo el código fuente está
en ese mismo repositorio, a la vista de quien quiera revisarlo.

## Cómo comprobar que el fichero es el bueno

Junto a cada versión se publica un fichero **`SHA256SUMS.txt`** con la «huella»
(SHA-256) de cada descarga. Si el fichero que tienes da la misma huella, es
exactamente el que se publicó; si alguien le hubiera cambiado un solo byte, la
huella sería otra.

1. Descarga también `SHA256SUMS.txt` de la misma versión.
2. Abre la carpeta donde están las descargas, haz clic en la barra de la
   dirección, escribe `powershell` y pulsa Intro.
3. Escribe esto (cambiando el nombre por el del fichero que bajaste):

   ```powershell
   Get-FileHash .\Farmadex-X.Y.Z-setup.exe
   ```

4. Compara el número largo que sale en la columna `Hash` con el que aparece al
   lado de ese mismo nombre en `SHA256SUMS.txt`. Tienen que ser **idénticos**.
   Si no lo son, no lo abras y descárgalo otra vez desde la página de versiones.

Si prefieres que lo compare el ordenador por ti, esta orden dice `True` si
coinciden y `False` si no:

```powershell
$f = "Farmadex-X.Y.Z-setup.exe"
(Get-FileHash $f).Hash -eq ((Get-Content SHA256SUMS.txt | Select-String $f) -split '\s+')[0]
```

Como comprobación extra, puedes subir el fichero a [VirusTotal](https://www.virustotal.com),
que lo pasa por muchos antivirus a la vez. Con programas nuevos y sin firma es normal
que alguno poco conocido dé un aviso genérico; lo que importa es que la huella coincida.

## Qué lee Farmadex

- **El registro que escribe el propio juego (`EE.log`)**, solo para saber cuándo
  abres una reliquia o acabas una misión. Ese fichero contiene tu correo y tu IP:
  Farmadex solo busca en él unos pocos mensajes del juego y **no guarda ni envía
  nada de él**.
- **La pantalla, solo cuando hace falta**: las recompensas de una reliquia, el
  objeto que tienes bajo el ratón y, si lo activas en Ajustes, tu Perfil y tu
  Inventario. Esas capturas se leen en tu ordenador y se descartan; no se
  guardan ni se envían a nadie.
- **Datos públicos de internet**: el catálogo de objetos y las tablas de drops
  (de WFCD y de Digital Extremes), lo que está pasando ahora en el juego, precios
  de warframe.market y si hay una versión nueva de Farmadex en GitHub.

## Qué guarda en tu ordenador

Solo en su propia carpeta, `%LOCALAPPDATA%\Farmadex`:

- tus ajustes (incluidos los colores y tamaños que elijas),
- tus objetivos,
- el catálogo descargado,
- y un registro de errores para poder ayudarte si algo falla.

Nada de eso sale de tu ordenador, salvo el informe que tú decidas enviar con
«Guardar informe para enviar», que no incluye `EE.log` ni datos de tu cuenta.
Al actualizar Farmadex, esa carpeta no se toca, así que conservas todo.

## Qué NO toca

- No lee ni escribe la **memoria del juego**.
- No mira ni cambia su **conexión** ni su tráfico de red.
- No modifica los **ficheros del juego** ni inyecta nada en él.
- No pulsa teclas ni automatiza nada por ti.
- No entra en tu **cuenta** y nunca te pide la contraseña.

## Y qué dice Digital Extremes

Digital Extremes tiene una página de soporte sobre los programas de terceros:
[Third Party Software and You](https://support.warframe.com/hc/en-us/articles/360030014351-Third-Party-Software-and-You).
Según esa página, DE no respalda el uso de ningún programa de terceros y quien
los usa lo hace bajo su propia responsabilidad («at your own risk»).

Farmadex intenta quedarse lejos de lo que esa política persigue (leer o tocar la
memoria del juego, modificarlo, automatizar partidas), y hace lo mismo que llevan
años haciendo herramientas conocidas de la comunidad: mirar la pantalla y el
registro del juego. Aun así:

- **Farmadex no está aprobado ni respaldado por Digital Extremes.**
- **Nadie puede prometerte que no haya ningún riesgo.** La decisión de usarlo es tuya.

Farmadex no está afiliado a Digital Extremes. Warframe y todo su contenido son
propiedad de Digital Extremes.

## ¿Tienes una duda?

Farmadex lo hace **vaas**. Puedes preguntarle en su canal de Twitch,
[twitch.tv/vaas1897](https://www.twitch.tv/vaas1897), o abrir un aviso en
[GitHub](https://github.com/angelsanchez97/farmadex/issues).
