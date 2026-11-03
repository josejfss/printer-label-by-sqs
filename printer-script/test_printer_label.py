import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from printer_label import (
    create_label,
    consume_sqs_messages,
    customer_name_from_message,
    get_default_printer,
    get_label_printer,
    normalize_customer_name,
    print_label,
)

PREFERRED_LABEL_PRINTER = "Munbyn ITPP941P"

class CreateLabelTests(unittest.TestCase):
    def test_normalizes_customer_name(self):
        self.assertEqual(normalize_customer_name("  María José  Núñez "), "MARIA JOSE NUNEZ")

    def test_extracts_customer_name_from_sqs_json(self):
        body = json.dumps(
            {
                "user": "operador1",
                "purchase_detail": {"customer_name": "Candy Carrillo"},
            }
        )
        self.assertEqual(customer_name_from_message(body), "CANDY CARRILLO")

    @patch("printer_label.print_label", return_value="impreso")
    @patch("printer_label.create_label", return_value=Path("label.pdf"))
    @patch("printer_label.create_sqs_client")
    def test_sqs_message_is_deleted_after_printing(
        self, client_factory, create, _print
    ):
        client = client_factory.return_value
        client.receive_message.return_value = {
            "Messages": [
                {
                    "MessageId": "message-1",
                    "ReceiptHandle": "receipt-1",
                    "Body": json.dumps(
                        {
                            "user": "operador1",
                            "purchase_detail": {
                                "customer_name": "José Núñez"
                            }
                        }
                    ),
                }
            ]
        }

        processed = consume_sqs_messages(
            "https://example.test/queue",
            "Munbyn",
            "operador1",
            1,
            Path("label.pdf"),
            once=True,
        )

        self.assertEqual(processed, 1)
        create.assert_called_once_with(Path("label.pdf"), "JOSE NUNEZ")
        client.delete_message.assert_called_once_with(
            QueueUrl="https://example.test/queue",
            ReceiptHandle="receipt-1",
        )

    @patch("printer_label.time.sleep")
    @patch("printer_label.print_label")
    @patch("printer_label.create_sqs_client")
    def test_message_for_another_user_is_returned_immediately(
        self, client_factory, print_mock, sleep
    ):
        client = client_factory.return_value
        client.receive_message.return_value = {
            "Messages": [
                {
                    "MessageId": "message-2",
                    "ReceiptHandle": "receipt-2",
                    "Body": json.dumps(
                        {
                            "user": "operador2",
                            "purchase_detail": {
                                "customer_name": "Otro Cliente"
                            },
                        }
                    ),
                }
            ]
        }

        processed = consume_sqs_messages(
            "https://example.test/queue",
            "Munbyn",
            "operador1",
            1,
            Path("label.pdf"),
            once=True,
        )

        self.assertEqual(processed, 0)
        client.change_message_visibility.assert_called_once_with(
            QueueUrl="https://example.test/queue",
            ReceiptHandle="receipt-2",
            VisibilityTimeout=0,
        )
        sleep.assert_called_once_with(2)
        print_mock.assert_not_called()
        client.delete_message.assert_not_called()

    def test_creates_five_by_two_centimeter_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "label.pdf"
            create_label(output, "PRUEBA", "Etiqueta")
            content = output.read_bytes()

        self.assertTrue(content.startswith(b"%PDF-1.4"))
        self.assertIn(b"/MediaBox [0 0 141.732 56.693]", content)
        self.assertIn(b"(PRUEBA) Tj", content)
        self.assertTrue(content.endswith(b"%%EOF\n"))

    def test_escapes_pdf_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "label.pdf"
            create_label(output, r"Producto (A)\B")
            content = output.read_bytes()

        self.assertIn(rb"(Producto) Tj", content)
        self.assertIn(rb"(\(A\)\\B) Tj", content)

    def test_reduces_font_size_for_long_text(self):
        with tempfile.TemporaryDirectory() as directory:
            short_pdf = Path(directory) / "short.pdf"
            long_pdf = Path(directory) / "long.pdf"
            create_label(short_pdf, "CORTO")
            create_label(
                long_pdf,
                "ESTE ES UN TEXTO MUCHO MAS LARGO PARA LA ETIQUETA",
            )

            short_content = short_pdf.read_text("latin-1")
            long_content = long_pdf.read_text("latin-1")

        self.assertIn("/F1 20.00 Tf", short_content)
        self.assertGreater(long_content.count(" Tj"), 1)
        printed_lines = re.findall(r"\(([^()]*)\) Tj", long_content)
        self.assertEqual(
            " ".join(printed_lines),
            "ESTE ES UN TEXTO MUCHO MAS LARGO PARA LA ETIQUETA",
        )

    def test_splits_a_long_word_without_losing_characters(self):
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "long-word.pdf"
            create_label(output, text)
            content = output.read_text("latin-1")

        printed_fragments = re.findall(r"\(([^()]*)\) Tj", content)
        self.assertGreater(len(printed_fragments), 1)
        self.assertEqual("".join(printed_fragments), text)

    @patch("printer_label._get_windows_default_printer")
    @patch("printer_label.platform.system", return_value="Windows")
    def test_get_default_printer_uses_windows_detection(
        self, _system, windows_default
    ):
        windows_default.return_value = PREFERRED_LABEL_PRINTER

        self.assertEqual(get_default_printer(), PREFERRED_LABEL_PRINTER)

    @patch("printer_label.list_printers")
    def test_get_label_printer_prefers_installed_munbyn(self, printers):
        printers.return_value = ["PDF24", PREFERRED_LABEL_PRINTER]

        self.assertEqual(get_label_printer(), PREFERRED_LABEL_PRINTER)

    @patch("printer_label.get_default_printer", return_value="PDF24")
    @patch("printer_label.list_printers", return_value=["PDF24"])
    def test_get_label_printer_falls_back_to_system_default(
        self, _printers, _default
    ):
        self.assertEqual(get_label_printer(), "PDF24")

    @patch("printer_label.subprocess.run")
    def test_print_label_uses_ghostscript_with_label_dimensions(self, run):
        run.return_value.returncode = 0
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            ghostscript = directory_path / "gswin64c.exe"
            pdf = directory_path / "label.pdf"
            ghostscript.touch()
            pdf.write_bytes(b"%PDF")

            with patch("printer_label.GHOSTSCRIPT_PATHS", (ghostscript,)):
                response = print_label(
                    pdf, PREFERRED_LABEL_PRINTER, copies=2
                )

        self.assertIn("50 x 20 mm", response)
        self.assertEqual(run.call_count, 2)
        arguments = run.call_args.args[0]
        self.assertIn("-dDEVICEWIDTHPOINTS=142", arguments)
        self.assertIn("-dDEVICEHEIGHTPOINTS=57", arguments)
        self.assertIn("-dAutoRotatePages=/None", arguments)
        self.assertIn(f"-sOutputFile=%printer%{PREFERRED_LABEL_PRINTER}", arguments)


if __name__ == "__main__":
    unittest.main()
