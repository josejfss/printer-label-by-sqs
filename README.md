# Impresora de etiquetas 5 × 2 cm

Programa en Python, sin dependencias externas, para generar e imprimir etiquetas
de 5 centímetros de ancho por 2 centímetros de alto en Windows o mediante CUPS
en macOS y Linux.

## 1. Ver las impresoras instaladas

```bash
python3 printer_label.py printers
```

El nombre mostrado debe copiarse exactamente en el comando de impresión.

## 2. Generar una etiqueta sin imprimir

```bash
python3 printer_label.py generate \
  --text "PRUEBA" \
  --subtitle "Etiqueta 5 x 2 cm"
```

El archivo se crea en `output/etiqueta.pdf`. Ábrelo para verificar el diseño.
Los textos largos se dividen automáticamente por palabras en varias líneas. El
tamaño de la fuente y la posición vertical también se calculan para mantener
todo el contenido centrado y dentro de los márgenes de la etiqueta.

## 3. Imprimir una etiqueta

Instala primero el cliente de AWS:

```bash
py -3 -m pip install -r requirements.txt
```

Completa `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` y `PRINTER_USER` en `.env`.
Cada área de impresión debe tener su propio valor de `PRINTER_USER`. El archivo
ya incluye la región y URL de la cola. Luego inicia el consumidor:

```bash
py -3 printer_label.py print
```

El proceso espera mensajes mediante long polling. De cada JSON obtiene
`purchase_detail.customer_name`, convierte el nombre a mayúsculas, elimina
tildes, genera la etiqueta y la imprime. El mensaje se elimina de SQS únicamente
después de enviar correctamente la impresión.

El campo `user` del mensaje debe coincidir con `PRINTER_USER`. Si pertenece a
otra área, el mensaje vuelve inmediatamente a estar visible en la cola y el
consumidor espera dos segundos antes de solicitar otro mensaje.

Para procesar como máximo un mensaje y finalizar:

```bash
py -3 printer_label.py print --once
```

Sin `--printer`, usa automáticamente `Munbyn ITPP941P`. Para elegir otra
impresora, agrega `--printer "Nombre de impresora"`. Para varias copias por
mensaje, agrega `--copies 3`.

En Windows, el programa utiliza el Ghostscript incluido con PDF24 para imponer
el tamaño físico de 50 × 20 mm, ajustar el contenido a una sola etiqueta y
evitar la rotación automática. PDF24 Reader queda como método de respaldo.

El programa solicita a CUPS un papel personalizado de `50x20mm`, coincidente con
las dimensiones exactas del PDF.

## Pruebas

```bash
python3 -m unittest -v
```
