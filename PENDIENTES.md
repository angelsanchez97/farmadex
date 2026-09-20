# Pendiente

Lo que el usuario ha pedido y todavía no está hecho. Se va vaciando según se
cierra cada cosa.

## Para lanzar cuando terminen los trabajos en curso

### Aguantar las actualizaciones de Warframe sin romperse

Warframe se actualiza cada pocas semanas y a veces lo hace en grande. Hay que
revisar qué partes de Farmadex se rompen cuando eso pasa y dejarlas blindadas:

- Los datos vienen de WFCD y de las tablas de Digital Extremes, que tardan
  horas o días en ponerse al día tras un parche: qué pasa mientras tanto y qué
  se le enseña al usuario.
- Categorías, campos o nombres nuevos en el catálogo que hoy no se contemplan
  (ya pasó con los recursos que salían como piezas).
- Nodos nuevos en el mapa estelar, eras de reliquia nuevas, tipos de misión que
  no están en el glosario.
- Claves nuevas o renombradas en el estado del mundo.
- Cambios en la interfaz del juego que descoloquen el OCR de recompensas
  (posición de las tarjetas, tipografía, resolución).
- Cambios en los mensajes de `EE.log` que se usan como disparadores.
- Que la aplicación avise cuando detecte que algo dejó de cuadrar, en vez de
  enseñar datos viejos como si fueran buenos.

### Funcionar en los tres modos de pantalla

Hoy está probado y documentado solo en ventana sin bordes.

- **Modo ventana**: debería funcionar ya (ventana siempre encima, captura por el
  rectángulo de cliente del juego), pero hay que probarlo de verdad y arreglar
  lo que salga: posición del overlay, coordenadas del OCR y el recuadro del
  cursor cuando el juego no ocupa toda la pantalla.
- **Pantalla completa sin bordes**: funciona, es lo que usa el usuario.
- **Pantalla completa exclusiva**: ninguna ventana de Windows se dibuja encima,
  y la única forma de conseguirlo es inyectarse en el motor del juego, cosa que
  este proyecto no hace ni va a hacer. Lo que sí toca: detectar ese modo, decirlo
  con claridad en vez de dejar al usuario pensando que la aplicación falla, y
  ofrecer la salida razonable (sacar el overlay en un segundo monitor si lo hay).
