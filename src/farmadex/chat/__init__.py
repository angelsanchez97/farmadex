"""Precios al instante de lo que sale en el chat del juego y de lo que se copia.

- `nombres`: texto (nombre de objeto en cualquier idioma del indice) -> slug de warframe.market.
- `texto`: rangos, sets, precios pedidos y agrietados dentro de un texto; listas de venta.
- `precios`: adaptador al contrato `online.precios_diarios` (snapshot local, sin red).
- `enlace`: enlaces del chat bajo el raton (color + OCR de solo el enlace).
- `portapapeles`: listas de venta copiadas (por evento, apagado por defecto).
- `historial`: lo mirado en el chat (apagado por defecto, solo local, borrable).
- `rivens`: horquilla de agrietados parecidos, en segundo plano.
"""
