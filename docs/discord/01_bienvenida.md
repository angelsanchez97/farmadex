--- MENSAJE 1 ---
# 🎯 ¿Qué es Farmadex?

Farmadex es un overlay en español para Warframe. Se abre encima del juego con **Ctrl+Alt+W**, escribes lo que buscas y te dice adónde ir a farmearlo y cuánto vas a tardar, más o menos.

Un par de ejemplos de para qué sirve:

- Escribes **"sensores neuronales"** y lo primero que sale es Alad V, en Júpiter, con el tiempo que te va a costar sacarlo ahí frente a otras misiones. Nada de tener la wiki abierta en la otra pantalla.
- Escribes **"sierra"** y no te lías entre el mod, el arma y el aspecto que se llaman igual: cada tipo de objeto lleva su color.
- Si buscas una pieza Prime, te dice en qué reliquias cae, cuáles están en bóveda y qué se pide por ella en warframe.market.
- Tiene una pestaña de **Mis metas** para llevar tu lista de farmeo, una de **Mundo** para las fisuras y ciclos del momento (con avisos si quieres), y hasta lee los mods de tu build o evalúa un riven agrietado con un atajo.

Es gratis, lo hace un jugador (vaas) y todo el código está a la vista.

**Descarga:** https://github.com/angelsanchez97/farmadex/releases/latest

En los próximos mensajes: cómo instalarlo, qué hacer la primera vez y por qué Windows va a poner mala cara al abrirlo (tiene explicación, tranquilo).

--- MENSAJE 2 ---
# 📥 Cómo descargarlo e instalarlo

1. Baja el instalador desde la última versión: https://github.com/angelsanchez97/farmadex/releases/latest
   (si prefieres no instalar nada, ahí mismo hay un `.zip` portable).
2. Ábrelo. Lo normal es que Windows te enseñe un aviso azul antes de dejarte seguir — es SmartScreen, te lo explico en el siguiente mensaje. No te va a pedir permisos de administrador.
3. La primera vez que arranca, Farmadex descarga los datos del juego (objetos, drops...). Tarda un rato, pero es solo esa vez.

Una condición importante: Warframe tiene que estar en **ventana** o **ventana sin bordes**. En pantalla completa ningún programa puede dibujar encima, ni Farmadex ni ningún otro overlay. Se cambia en Opciones > Pantalla, dentro del propio juego.

--- MENSAJE 3 ---
# 🚀 La primera vez que lo abres

Te recibe una bienvenida que te cuenta qué es Farmadex, lo básico para empezar, si es seguro y las dudas más típicas. Después te ofrece un recorrido guiado por la ventana que te va señalando cada parte: Buscar, Mis metas, Mundo, Herramientas...

No hace falta que te lo leas todo de golpe: las dos se pueden volver a abrir cuando quieras desde **Ajustes > Ayuda**, o con el botón "Guía".

Un aviso para que no te asustes: la primera búsqueda que hagas puede tardar un poco más de lo normal mientras Farmadex termina de prepararse por dentro. Es normal, y solo pasa esa vez (a veces también al pasar a una versión con muchos cambios).

--- MENSAJE 4 ---
# 🛡️ El aviso azul de Windows (SmartScreen)

Al abrir el instalador es muy probable que te salga un aviso azul: **"Windows protegió tu PC"**. No es que tenga un virus, es que Farmadex no lleva una firma digital de pago (esos certificados cuestan bastante dinero cada año, y esto lo hace una sola persona, gratis).

Para seguir:
1. Pulsa **"Más información"**.
2. Pulsa **"Ejecutar de todas formas"**.

Y ya está, se instala normal.

Si quieres quedarte tranquilo del todo:
- Descárgalo **solo** desde aquí: https://github.com/angelsanchez97/farmadex/releases/latest — si te lo pasan por otro Discord o una web de descargas, nadie te garantiza que no lo hayan tocado.
- Comprueba el fichero con `SHA256SUMS.txt` (te explico cómo en el siguiente mensaje).
- Todo el código está publicado, a la vista de quien quiera mirarlo.

Más detalle: https://github.com/angelsanchez97/farmadex/blob/main/docs/SEGURIDAD.md

--- MENSAJE 5 ---
# 🔍 Comprobar que el fichero es el bueno

Junto a cada versión hay un fichero **`SHA256SUMS.txt`** con la "huella" de cada descarga. Si la huella de tu fichero coincide con la que hay ahí, es exactamente el que se publicó — si alguien le hubiera tocado un solo byte, la huella sería otra.

Cómo sacarla:
1. Descarga también `SHA256SUMS.txt` de esa misma versión.
2. En la carpeta donde están las descargas, haz clic en la barra de dirección, escribe `powershell` y pulsa Intro.
3. Escribe esto (cambiando el nombre por el del fichero que bajaste):
```
Get-FileHash .\Farmadex-X.Y.Z-setup.exe
```
4. Compara el número largo (columna `Hash`) con el que aparece junto a ese mismo nombre en `SHA256SUMS.txt`. Tienen que ser **idénticos**. Si no coinciden, no lo abras y vuelve a descargarlo desde la página oficial.

Si prefieres que lo compruebe el ordenador por ti, esto dice `True` o `False`:
```
$f = "Farmadex-X.Y.Z-setup.exe"
(Get-FileHash $f).Hash -eq ((Get-Content SHA256SUMS.txt | Select-String $f) -split '\s+')[0]
```

Más detalle: https://github.com/angelsanchez97/farmadex/blob/main/docs/SEGURIDAD.md
