# Impresora de etiquetas 5 × 2 cm

Programa en Python, sin dependencias externas adicionales para la generación de
etiquetas, para generar e imprimir etiquetas de 5 centímetros de ancho por
2 centímetros de alto en Windows y macOS. El soporte para Linux todavía no ha
sido probado con ninguna distribución.

## IMPORTANTE: es necesario tener conexión a internet

**El programa necesita una conexión a internet activa para comunicarse con AWS
SQS, recibir los mensajes y procesar las etiquetas. Sin conexión, el consumidor
no podrá recibir ni imprimir nuevas etiquetas.**

## 1. Preparar y configurar la impresora en Windows

1. Descarga e instala los controladores de la impresora **Munbyn ITPP941P**
   desde la [página oficial de controladores y SDK de Munbyn](https://support.munbyn.com/hc/en-us/articles/6092502480787-Printer-Drivers-SDK-Download).
2. Conecta y enciende la impresora. En Windows, abre **Configuración >
   Bluetooth y dispositivos > Impresoras y escáneres** y desactiva la opción
   **Permitir que Windows administre mi impresora predeterminada**.
3. Busca **Munbyn ITPP941P** en la lista de impresoras y establécela como
   impresora predeterminada.
4. En las preferencias o propiedades de impresión de la Munbyn, crea un
   tamaño de papel personalizado llamado `etiqueta`, con **50 mm de ancho** y
   **20 mm de alto**, y selecciónalo como tamaño de papel.
5. Realiza una prueba de impresión desde Microsoft Word usando el tamaño
   `etiqueta` para confirmar que la impresora, la orientación y las
   dimensiones funcionan correctamente antes de iniciar el programa.

> **Observación:** Si la impresora ya estaba instalada y durante la prueba de
> impresión se utilizó la impresora que Windows registró como
> `Munbyn ITPP941P (Copiar 1)`, actualiza la constante
> `PREFERRED_LABEL_PRINTER` en
> [`printer_label.py`](./printer-script/printer_label.py) para que coincida
> exactamente con ese nombre:
>
> ```python
> PREFERRED_LABEL_PRINTER = "Munbyn ITPP941P (Copiar 1)"
> ```
>
> El nombre debe ser igual al que aparece en **Impresoras y escáneres**.

En Windows es obligatorio tener instalado **PDF24 Creator**, ya que el script
lo utiliza junto con Ghostscript para ajustar el PDF al tamaño físico de
50 × 20 mm antes de enviarlo a la impresora.

Si PDF24 Creator no está instalado:

1. Descárgalo desde la [página oficial de PDF24 Creator](https://www.pdf24.org/es/creator).
2. Ejecuta el instalador y acepta los componentes recomendados, incluido
   Ghostscript.
3. Reinicia Windows si el instalador lo solicita.
4. Abre PDF24 Creator una vez para completar la configuración y confirma que
   puedes abrir un archivo PDF.
5. Ejecuta el comando `generate` del paso 5 para generar una etiqueta de
   prueba y después continúa con el paso de impresión.

## 2. Requisitos de Python y entorno virtual

Se requiere **Python 3.10 o posterior**. En Windows, verifica que esté
instalado con:

```powershell
py --version
```

La práctica recomendada es utilizar un entorno virtual para aislar las
dependencias de este proyecto. Desde la carpeta `printer-script`, créalo y
actívalo:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Cuando esté activo, el prompt de PowerShell mostrará `(.venv)`. Instala las
dependencias del proyecto dentro del entorno virtual:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Para salir del entorno virtual:

```powershell
deactivate
```

Cada vez que abras una nueva terminal, vuelve a la carpeta del proyecto y
activa `.venv` antes de ejecutar el programa:

```powershell
.\.venv\Scripts\Activate.ps1
```

Si PowerShell impide ejecutar el script de activación, permite scripts para tu
usuario actual y vuelve a activarlo:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 3. Configurar las variables de entorno

Desde esta carpeta, crea el archivo `.env` a partir de `.env.example`:

```powershell
Copy-Item .env.example .env
```

Edita `.env` y completa las siguientes variables:

| Variable | Descripción |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | Access key de AWS con permisos para leer y eliminar mensajes de la cola SQS. |
| `AWS_SECRET_ACCESS_KEY` | Secret key correspondiente a la access key. |
| `AWS_REGION` | Región de AWS de la cola; por defecto `us-east-1`. |
| `SQS_QUEUE_URL` | URL de la cola SQS que debe consumir el programa. |
| `PRINTER_USER` | Usuario o área asignado a esta estación; debe coincidir con el campo `user` de los mensajes. |
| `AWS_SESSION_TOKEN` | Opcional; úsalo cuando las credenciales de AWS sean temporales. |

No compartas ni subas `.env` al repositorio, porque contiene credenciales.

## 4. Ver las impresoras instaladas

```bash
python printer_label.py printers
```

El nombre mostrado debe copiarse exactamente en el comando de impresión.

## 5. Generar una etiqueta sin imprimir

```bash
python printer_label.py generate \
  --text "PRUEBA" \
  --subtitle "Etiqueta 5 x 2 cm"
```

El archivo se crea en `output/etiqueta.pdf`. Ábrelo para verificar el diseño.
Los textos largos se dividen automáticamente por palabras en varias líneas. El
tamaño de la fuente y la posición vertical también se calculan para mantener
todo el contenido centrado y dentro de los márgenes de la etiqueta.

> **Observación:** El consumidor obtiene de SQS mensajes JSON con información
> del escaneo y de la compra. Los campos más importantes para este script son:
>
> - **`user`**: debe coincidir exactamente con el valor configurado en la
>   variable de entorno `PRINTER_USER`. Si no coincide, el mensaje no se
>   procesa en esa estación.
> - **`purchase_detail.customer_name`**: contiene el nombre de la persona que
>   se imprime en la etiqueta. El script lo convierte a mayúsculas y elimina
>   las tildes.
>
> La estructura esperada del mensaje es:
>
> ```json
> {
>   "message": "Mensaje informativo",
>   "date_scanned": "2026-01-15T10:30:00Z",
>   "status": "scanned",
>   "user": "operador1",
>   "event_uuid": "00000000-0000-0000-0000-000000000000",
>   "purchase_detail": {
>     "order_uuid": "00000000-0000-0000-0000-000000000000",
>     "customer_name": "Nombre de la persona",
>     "customer_email": "cliente@example.com",
>     "purchase_date": "2026-01-15T10:25:00Z",
>     "ticket_name": "Entrada general",
>     "seats_label": "A-10",
>     "customer_data": {}
>   }
> }
> ```

## 6. Imprimir una etiqueta

Cada área de impresión debe tener su propio valor de `PRINTER_USER`. Luego
inicia el consumidor:

```bash
python printer_label.py print
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
python printer_label.py print --once
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
python -m unittest -v
```
