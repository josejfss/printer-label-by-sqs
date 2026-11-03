#!/usr/bin/env python3
"""Genera e imprime etiquetas PDF de 5 x 2 cm usando CUPS/macOS o Windows."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

POINTS_PER_MM = 72 / 25.4
LABEL_WIDTH = 50 * POINTS_PER_MM
LABEL_HEIGHT = 20 * POINTS_PER_MM
LABEL_HORIZONTAL_MARGIN = 5
PREFERRED_LABEL_PRINTER = "Munbyn ITPP941P"
DEFAULT_SQS_QUEUE_URL = (
    "https://sqs.us-east-1.amazonaws.com/021891596191/"
    "proticket-printer-sqs-prd"
)
PDF24_READER_PATHS = (
    Path(r"C:\Program Files\PDF24\pdf24-Reader.exe"),
    Path(r"C:\Program Files (x86)\PDF24\pdf24-Reader.exe"),
)
GHOSTSCRIPT_PATHS = (
    Path(r"C:\Program Files\PDF24\gs\bin\gswin64c.exe"),
    Path(r"C:\Program Files (x86)\PDF24\gs\bin\gswin64c.exe"),
)


def _escape_pdf_text(value: str) -> str:
    """Escapa texto para una cadena literal PDF."""
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text_width_units(value: str, bold: bool = False) -> float:
    """Estima el ancho de texto Helvetica en unidades relativas a la fuente."""
    width = 0.0
    for character in value:
        if character.isspace():
            factor = 0.28
        elif character in "ilI.,:;!'|":
            factor = 0.28
        elif character in "mwMW@%&":
            factor = 0.86
        elif character.isupper() or character.isdigit():
            factor = 0.62
        else:
            factor = 0.52
        width += factor
    return width * (1.04 if bold else 1.0)


def _wrap_text(
    value: str,
    font_size: float,
    bold: bool,
    available_width: float,
) -> list[str]:
    """Divide texto por palabras y parte palabras que no caben en una línea."""
    if not value:
        return []

    lines: list[str] = []
    current = ""
    for word in value.split():
        pending = word
        while pending:
            candidate = f"{current} {pending}".strip()
            if _text_width_units(candidate, bold) * font_size <= available_width:
                current = candidate
                pending = ""
                continue

            if current:
                lines.append(current)
                current = ""
                continue

            split_at = 1
            for index in range(2, len(pending) + 1):
                fragment = pending[:index]
                if _text_width_units(fragment, bold) * font_size > available_width:
                    break
                split_at = index
            lines.append(pending[:split_at])
            pending = pending[split_at:]

    if current:
        lines.append(current)
    return lines


def _fit_wrapped_text(
    value: str,
    maximum_size: float,
    minimum_size: float,
    maximum_lines: int,
    bold: bool,
) -> tuple[list[str], float]:
    """Busca la fuente más grande que permite usar el número máximo de líneas."""
    available_width = LABEL_WIDTH - (2 * LABEL_HORIZONTAL_MARGIN)
    size = maximum_size
    while size >= minimum_size:
        lines = _wrap_text(value, size, bold, available_width)
        if len(lines) <= maximum_lines:
            return lines, size
        size -= 0.5

    # Para entradas excepcionales, sigue reduciendo antes que cortar el texto.
    while size > 1:
        lines = _wrap_text(value, size, bold, available_width)
        if len(lines) <= maximum_lines:
            return lines, size
        size -= 0.5
    return _wrap_text(value, 1, bold, available_width), 1


def _pdf_text_lines(
    lines: list[str],
    font_name: str,
    font_size: float,
    center_y: float,
    bold: bool,
) -> list[str]:
    """Genera los comandos PDF para un bloque multilínea centrado."""
    if not lines:
        return []
    line_height = font_size * 1.12
    first_baseline = (
        center_y + ((len(lines) - 1) * line_height / 2) - (font_size * 0.32)
    )
    commands = [f"/{font_name} {font_size:.2f} Tf"]
    for index, line in enumerate(lines):
        text_width = _text_width_units(line, bold) * font_size
        x = max(LABEL_HORIZONTAL_MARGIN, (LABEL_WIDTH - text_width) / 2)
        y = first_baseline - (index * line_height)
        commands.append(
            f"1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape_pdf_text(line)}) Tj"
        )
    return commands


def create_label(output: Path, title: str, subtitle: str = "") -> Path:
    """Crea un PDF de una página con tamaño exacto de 5 x 2 cm."""
    title_lines, title_size = _fit_wrapped_text(
        title,
        maximum_size=20,
        minimum_size=5,
        maximum_lines=2 if subtitle else 3,
        bold=True,
    )
    subtitle_lines, subtitle_size = _fit_wrapped_text(
        subtitle,
        maximum_size=9,
        minimum_size=4,
        maximum_lines=2,
        bold=False,
    )

    commands = ["BT"]
    commands.extend(
        _pdf_text_lines(
            title_lines,
            "F1",
            title_size,
            center_y=38 if subtitle else LABEL_HEIGHT / 2,
            bold=True,
        )
    )
    if subtitle:
        commands.extend(
            _pdf_text_lines(
                subtitle_lines,
                "F2",
                subtitle_size,
                center_y=11,
                bold=False,
            )
        )
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R "
            + f"/MediaBox [0 0 {LABEL_WIDTH:.3f} {LABEL_HEIGHT:.3f}] ".encode()
            + b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> "
            b"/Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pdf)
    return output


def list_printers() -> list[str]:
    """Devuelve los nombres de las impresoras configuradas."""
    printers: list[str] = []
    
    if platform.system() == "Windows":
        # En Windows, usar PowerShell para listar impresoras
        try:
            result = subprocess.run(
                ["powershell", "-Command", 
                 "Get-Printer | Select-Object -ExpandProperty Name"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line:
                        printers.append(line)
        except (FileNotFoundError, OSError):
            # Si PowerShell no está disponible, intentar con wmic
            try:
                result = subprocess.run(
                    ["wmic", "printer", "list", "brief"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines()[1:]:  # Saltar encabezado
                        line = line.strip()
                        if line:
                            # wmic devuelve: Name Status State
                            parts = line.split()
                            if parts:
                                printers.append(parts[0])
            except (FileNotFoundError, OSError):
                pass
    else:
        # En macOS y Linux, usar CUPS
        try:
            result = subprocess.run(
                ["lpstat", "-p"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.splitlines():
                match = re.match(r"printer\s+(\S+)", line)
                if match:
                    printers.append(match.group(1))
        except FileNotFoundError:
            pass
    
    return printers


def print_label(pdf_path: Path, printer: str, copies: int = 1) -> str:
    """Envía el PDF a una impresora instalada y devuelve la respuesta."""
    if copies < 1:
        raise ValueError("El número de copias debe ser mayor que cero.")
    
    if platform.system() == "Windows":
        pdf_path_resolved = pdf_path.resolve()
        if not pdf_path_resolved.is_file():
            raise RuntimeError(f"No existe el archivo para imprimir: {pdf_path_resolved}")

        ghostscript = next(
            (path for path in GHOSTSCRIPT_PATHS if path.is_file()),
            None,
        )
        if ghostscript:
            try:
                for _ in range(copies):
                    result = subprocess.run(
                        [
                            str(ghostscript),
                            "-dBATCH",
                            "-dNOPAUSE",
                            "-dSAFER",
                            "-sDEVICE=mswinpr2",
                            "-dNoCancel",
                            f"-dDEVICEWIDTHPOINTS={round(LABEL_WIDTH)}",
                            f"-dDEVICEHEIGHTPOINTS={round(LABEL_HEIGHT)}",
                            "-dFIXEDMEDIA",
                            "-dPDFFitPage",
                            "-dAutoRotatePages=/None",
                            f"-sOutputFile=%printer%{printer}",
                            str(pdf_path_resolved),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                    )
                    if result.returncode != 0:
                        message = result.stderr.strip() or result.stdout.strip()
                        raise RuntimeError(
                            message
                            or f"Ghostscript terminó con código {result.returncode}."
                        )
                return (
                    "Trabajo enviado a la impresora en formato 50 x 20 mm "
                    "mediante Ghostscript."
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    f"Ghostscript agotó el tiempo al imprimir en '{printer}'."
                ) from error
            except OSError as error:
                raise RuntimeError(
                    f"No se pudo ejecutar Ghostscript: {error}"
                ) from error

        pdf24_reader = next(
            (path for path in PDF24_READER_PATHS if path.is_file()),
            None,
        )
        if pdf24_reader:
            try:
                for _ in range(copies):
                    result = subprocess.run(
                        [
                            str(pdf24_reader),
                            "/printTo",
                            printer,
                            str(pdf_path_resolved),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                    )
                    if result.returncode != 0:
                        message = result.stderr.strip() or result.stdout.strip()
                        raise RuntimeError(
                            message
                            or f"PDF24 Reader terminó con código {result.returncode}."
                        )
                return "Trabajo enviado a la impresora mediante PDF24 Reader."
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    f"PDF24 Reader agotó el tiempo al imprimir en '{printer}'."
                ) from error
            except OSError as error:
                raise RuntimeError(
                    f"No se pudo ejecutar PDF24 Reader: {error}"
                ) from error

        # Respaldo para equipos sin Ghostscript ni PDF24 Reader.
        try:
            shell_execute = ctypes.windll.shell32.ShellExecuteW
            shell_execute.restype = ctypes.c_void_p
            parameters = f'"{printer}"'

            for _ in range(copies):
                result = shell_execute(
                    None,
                    "printto",
                    str(pdf_path_resolved),
                    parameters,
                    str(pdf_path_resolved.parent),
                    0,
                )
                # ShellExecute devuelve valores <= 32 cuando no pudo iniciar
                # la aplicación asociada al tipo PDF.
                result_code = int(result or 0)
                if result_code <= 32:
                    raise RuntimeError(
                        "Windows no pudo enviar el PDF a "
                        f"'{printer}' (código ShellExecute {result_code}). "
                        "Instale PDF24 Reader o registre la acción de impresión "
                        "para archivos PDF."
                    )

            return "Trabajo enviado a la impresora."
        except (AttributeError, OSError) as error:
            raise RuntimeError(f"Windows no pudo iniciar la impresión: {error}") from error
    else:
        # En macOS y Linux, usar CUPS
        result = subprocess.run(
            [
                "lp",
                "-d",
                printer,
                "-n",
                str(copies),
                "-o",
                "media=Custom.50x20mm",
                "-o",
                "fit-to-page",
                str(pdf_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or "No se pudo enviar el trabajo a la impresora."
            raise RuntimeError(message)
        return result.stdout.strip()
    
    return "Trabajo enviado a la impresora."


def _get_windows_default_printer() -> str | None:
    """Consulta la impresora predeterminada del usuario actual en Windows."""
    try:
        get_default_printer = ctypes.windll.winspool.drv.GetDefaultPrinterW
        size = ctypes.c_ulong(0)

        # La primera llamada obtiene el tamaño necesario para el nombre.
        get_default_printer(None, ctypes.byref(size))
        if size.value:
            buffer = ctypes.create_unicode_buffer(size.value)
            if get_default_printer(buffer, ctypes.byref(size)):
                name = buffer.value.strip()
                if name:
                    return name
    except (AttributeError, OSError, ValueError):
        pass

    # Get-CimInstance sustituye a Get-WmiObject en PowerShell moderno.
    ps_command = (
        "Get-CimInstance -ClassName Win32_Printer "
        "-Filter 'Default=True' -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty Name"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Último recurso: Windows guarda "impresora,controlador,puerto" en Device.
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\Windows",
        ) as key:
            device, _ = winreg.QueryValueEx(key, "Device")
            name = str(device).split(",", 1)[0].strip()
            return name or None
    except (ImportError, OSError):
        return None


def get_default_printer() -> str | None:
    """Obtiene la impresora por defecto configurada en el sistema."""
    if platform.system() == "Windows":
        return _get_windows_default_printer()
    else:
        # En macOS y Linux, usar CUPS
        try:
            result = subprocess.run(
                ["lpstat", "-d"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                # Formato: "system default destination: printer_name"
                match = re.search(r":\s+(\S+)", result.stdout)
                if match:
                    return match.group(1)
        except FileNotFoundError:
            pass
    
    return None


def get_label_printer() -> str | None:
    """Obtiene la impresora de etiquetas instalada o la predeterminada."""
    installed_printers = list_printers()
    preferred_name = PREFERRED_LABEL_PRINTER.casefold()
    for printer in installed_printers:
        if printer.casefold() == preferred_name:
            return printer

    return get_default_printer()


def load_env_file(path: Path = Path(".env")) -> None:
    """Carga variables simples de un archivo .env sin sobrescribir el entorno."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def normalize_customer_name(value: str) -> str:
    """Convierte un nombre a mayúsculas, elimina tildes y normaliza espacios."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_accents.upper().split())


def customer_name_from_message(body: str) -> str:
    """Extrae y normaliza purchase_detail.customer_name de un mensaje JSON."""
    customer_name, _ = print_data_from_message(body)
    return customer_name


def print_data_from_message(body: str) -> tuple[str, str]:
    """Extrae el nombre del cliente y usuario de enrutamiento del mensaje."""
    try:
        payload = json.loads(body)
        customer_name = payload["purchase_detail"]["customer_name"]
        message_user = payload["user"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(
            "El mensaje SQS no contiene purchase_detail.customer_name "
            "y user válidos."
        ) from error
    if not isinstance(customer_name, str) or not customer_name.strip():
        raise ValueError("purchase_detail.customer_name está vacío o no es texto.")
    if not isinstance(message_user, str) or not message_user.strip():
        raise ValueError("user está vacío o no es texto.")
    return normalize_customer_name(customer_name), message_user.strip()


def create_sqs_client():
    """Crea el cliente SQS usando .env o la cadena estándar de AWS."""
    try:
        import boto3
    except ImportError as error:
        raise RuntimeError(
            "Falta boto3. Instálelo con: py -3 -m pip install -r requirements.txt"
        ) from error

    options = {"region_name": os.getenv("AWS_REGION", "us-east-1")}
    access_key = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
    if access_key and secret_key:
        options["aws_access_key_id"] = access_key
        options["aws_secret_access_key"] = secret_key
        session_token = os.getenv("AWS_SESSION_TOKEN", "").strip()
        if session_token:
            options["aws_session_token"] = session_token
    return boto3.client("sqs", **options)


def consume_sqs_messages(
    queue_url: str,
    printer: str,
    configured_user: str,
    copies: int,
    output: Path,
    once: bool = False,
) -> int:
    """Consume SQS y elimina cada mensaje solo después de imprimirlo."""
    sqs = create_sqs_client()
    processed = 0
    print(f"Esperando mensajes de SQS: {queue_url}")
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=120,
            )
        except Exception as error:
            raise RuntimeError(f"No se pudo recibir mensajes de SQS: {error}") from error
        messages = response.get("Messages", [])
        if not messages:
            if once:
                return processed
            continue

        message = messages[0]
        try:
            customer_name, message_user = print_data_from_message(message["Body"])
            if message_user.casefold() != configured_user.casefold():
                try:
                    sqs.change_message_visibility(
                        QueueUrl=queue_url,
                        ReceiptHandle=message["ReceiptHandle"],
                        VisibilityTimeout=0,
                    )
                except Exception as error:
                    raise RuntimeError(
                        f"No se pudo devolver el mensaje a SQS: {error}"
                    ) from error
                print(
                    f"Mensaje para '{message_user}' devuelto a la cola; "
                    f"esta área atiende a '{configured_user}'."
                )
                time.sleep(2)
                if once:
                    return processed
                continue

            print(f"Cliente recibido: {customer_name}")
            pdf_path = create_label(output, customer_name)
            print(f"Etiqueta creada: {pdf_path.resolve()}")
            print(print_label(pdf_path, printer, copies))
            try:
                sqs.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=message["ReceiptHandle"],
                )
            except Exception as error:
                raise RuntimeError(
                    f"La etiqueta se imprimió, pero no se pudo eliminar "
                    f"el mensaje de SQS: {error}"
                ) from error
            processed += 1
            print(f"Mensaje {message.get('MessageId', '')} procesado y eliminado.")
        except (KeyError, OSError, RuntimeError, ValueError) as error:
            print(
                f"Error procesando mensaje {message.get('MessageId', '')}: {error}",
                file=sys.stderr,
            )
            if once:
                raise

        if once:
            return processed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera e imprime etiquetas de 5 x 2 cm."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("printers", help="Muestra las impresoras instaladas.")

    generate = subparsers.add_parser("generate", help="Genera una etiqueta PDF.")
    generate.add_argument("--text", default="PRUEBA", help="Texto principal.")
    generate.add_argument("--subtitle", default="", help="Texto secundario.")
    generate.add_argument(
        "--output", type=Path, default=Path("output/etiqueta.pdf")
    )

    print_command = subparsers.add_parser(
        "print", help="Consume SQS e imprime los nombres recibidos."
    )
    print_command.add_argument("--printer", required=False, help="Nombre de impresora (usa la por defecto si no se especifica).")
    print_command.add_argument("--copies", type=int, default=1)
    print_command.add_argument(
        "--queue-url",
        default=None,
        help="URL de SQS; por defecto usa SQS_QUEUE_URL del archivo .env.",
    )
    print_command.add_argument(
        "--once",
        action="store_true",
        help="Procesa como máximo un mensaje y finaliza.",
    )
    print_command.add_argument(
        "--output", type=Path, default=Path("output/etiqueta.pdf")
    )
    return parser


def main() -> int:
    load_env_file()
    args = build_parser().parse_args()
    try:
        if args.command == "printers":
            printers = list_printers()
            if not printers:
                system = platform.system()
                print(f"No se encontraron impresoras instaladas en {system}.")
                return 1
            print(f"Impresoras disponibles ({platform.system()}):")
            print("\n".join(printers))
            return 0

        if args.command == "generate":
            pdf_path = create_label(args.output, args.text, args.subtitle)
            print(f"Etiqueta creada: {pdf_path.resolve()}")
            return 0

        if args.command == "print":
            # Usar la impresora especificada o la impresora de etiquetas instalada.
            printer = args.printer
            if not printer:
                printer = get_label_printer()
                if not printer:
                    print(
                        "Error: No se encontró la impresora de etiquetas ni "
                        "una impresora predeterminada.",
                        file=sys.stderr,
                    )
                    return 1
                print(f"Usando impresora de etiquetas: {printer}")
            configured_user = os.getenv("PRINTER_USER", "").strip()
            if not configured_user:
                raise ValueError(
                    "Debe configurar PRINTER_USER en el archivo .env."
                )
            queue_url = (
                args.queue_url
                or os.getenv("SQS_QUEUE_URL")
                or DEFAULT_SQS_QUEUE_URL
            )
            consume_sqs_messages(
                queue_url,
                printer,
                configured_user,
                args.copies,
                args.output,
                once=args.once,
            )
        return 0
    except KeyboardInterrupt:
        print("\nConsumidor detenido.")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
