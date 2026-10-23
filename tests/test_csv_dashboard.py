import csv
import io
import re
import tempfile
import unittest
from typing import Any

from app import create_app
from models.hashtag_model import get_dashboard_data


def make_csv(headers: list[str], rows: list[list[str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


class CsvDashboardModelTests(unittest.TestCase):
    def test_filters_hashtags_without_case_sensitivity(self) -> None:
        csv_content = make_csv(
            ["Descripción", "Hora de publicación", "Alcance", "Me gusta"],
            [
                ["#Vacante #Trabajo", "2026-08-01 10:00:00", "120", "7"],
                ["#VACANTE", "2026-08-02 10:00:00", "80", "3"],
                ["#ServicioSocial", "2026-08-03 10:00:00", "50", "2"],
            ],
        )

        dashboard = get_dashboard_data(csv_content, "instagram.csv", "vAcAnTe")

        self.assertEqual(dashboard["network"], "CSV")
        self.assertEqual(dashboard["post_count"], 2)
        self.assertEqual(dashboard["reach_total"], 200)
        self.assertEqual(dashboard["likes_total"], 10)
        self.assertEqual(
            dashboard["hashtags"], ["#serviciosocial", "#trabajo", "#vacante"]
        )
        self.assertEqual(
            [row["Descripción"] for row in dashboard["filtered_rows"]],
            ["#Vacante #Trabajo", "#VACANTE"],
        )

    def test_maps_facebook_reactions_and_preserves_original_headers(self) -> None:
        csv_content = make_csv(
            ["Título", "Descripción", "Alcance", "Reacciones", "Enlace permanente"],
            [
                [
                    "#VACANTE",
                    "Detalle del puesto",
                    "42",
                    "9",
                    "https://example.com/post",
                ],
            ],
        )

        dashboard = get_dashboard_data(csv_content, "facebook.csv")

        self.assertEqual(dashboard["network"], "Facebook")
        self.assertEqual(dashboard["post_count"], 1)
        self.assertEqual(dashboard["likes_total"], 9)
        self.assertEqual(dashboard["posts"][0]["category"], "#vacante")
        self.assertEqual(dashboard["posts"][0]["link_url"], "https://example.com/post")
        self.assertEqual(
            dashboard["csv_headers"],
            ["Título", "Descripción", "Alcance", "Reacciones", "Enlace permanente"],
        )

    def test_rejects_csv_with_invalid_metric(self) -> None:
        csv_content = make_csv(["Descripción", "Alcance"], [["#Vacante", "muchos"]])

        with self.assertRaisesRegex(ValueError, "no es un entero válido"):
            get_dashboard_data(csv_content, "instagram.csv")


class CsvDashboardRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.upload_directory = tempfile.TemporaryDirectory()
        app = create_app()
        app.config.update(
            TESTING=True,
            UPLOAD_FOLDER=self.upload_directory.name,
        )
        self.client = app.test_client()

    def tearDown(self) -> None:
        self.upload_directory.cleanup()

    def _both_network_csvs(self) -> tuple[bytes, bytes]:
        instagram_csv = make_csv(
            [
                "Nombre de usuario de la cuenta",
                "Descripción",
                "Hora de publicación",
                "Alcance",
                "Me gusta",
            ],
            [
                ["bolsa", "#Vacante", "2026-08-01 10:00:00", "120", "7"],
                ["bolsa", "#ServicioSocial", "2026-08-02 10:00:00", "50", "2"],
            ],
        )
        facebook_csv = make_csv(
            [
                "Título",
                "Descripción",
                "Hora de publicación",
                "Enlace permanente",
                "Alcance",
                "Reacciones",
            ],
            [
                [
                    "#Oportunidad",
                    "Vacante disponible",
                    "2026-08-01 10:00:00",
                    "https://example.com/oportunidad",
                    "42",
                    "9",
                ],
                [
                    "#Empleo",
                    "Nueva publicación",
                    "2026-08-02 10:00:00",
                    "https://example.com/empleo",
                    "20",
                    "4",
                ],
            ],
        )
        return instagram_csv, facebook_csv

    def test_uploads_two_networks_and_filters_each_table_independently(self) -> None:
        instagram_csv, facebook_csv = self._both_network_csvs()
        response = self.client.post(
            "/analizar",
            data={
                "instagram_csv": (io.BytesIO(instagram_csv), "instagram.csv"),
                "facebook_csv": (io.BytesIO(facebook_csv), "facebook.csv"),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Instagram", response.data)
        self.assertIn(b"Facebook", response.data)
        instagram_match = re.search(
            rb'name="instagram_upload_id" value="([0-9a-f]{32})"', response.data
        )
        facebook_match = re.search(
            rb'name="facebook_upload_id" value="([0-9a-f]{32})"', response.data
        )
        self.assertIsNotNone(instagram_match)
        self.assertIsNotNone(facebook_match)
        instagram_id = instagram_match.group(1).decode("ascii") if instagram_match else ""
        facebook_id = facebook_match.group(1).decode("ascii") if facebook_match else ""

        filtered_response = self.client.post(
            "/filtrar",
            data={
                "network": "facebook",
                "instagram_upload_id": instagram_id,
                "instagram_filename": "instagram.csv",
                "instagram_hashtag": "",
                "facebook_upload_id": facebook_id,
                "facebook_filename": "facebook.csv",
                "hashtag": "oPoRtUnIdAd",
            },
        )

        self.assertEqual(filtered_response.status_code, 200)
        self.assertIn(b"filtro: oPoRtUnIdAd", filtered_response.data)
        self.assertIn(b"Descargar Instagram en CSV", filtered_response.data)
        self.assertIn(b"Descargar Facebook en CSV", filtered_response.data)
        instagram_section, facebook_section = filtered_response.data.split(
            b'id="facebook-title"', maxsplit=1
        )
        self.assertIn(b"#serviciosocial", instagram_section)
        self.assertIn(b"#vacante", instagram_section)
        self.assertIn(b"#oportunidad", facebook_section)
        self.assertNotIn(b'class="category-name">#empleo', facebook_section)

    def test_exports_only_the_selected_network_and_filter(self) -> None:
        instagram_csv, facebook_csv = self._both_network_csvs()
        response = self.client.post(
            "/analizar",
            data={
                "instagram_csv": (io.BytesIO(instagram_csv), "instagram.csv"),
                "facebook_csv": (io.BytesIO(facebook_csv), "facebook.csv"),
            },
            content_type="multipart/form-data",
        )
        facebook_match = re.search(
            rb'name="facebook_upload_id" value="([0-9a-f]{32})"', response.data
        )
        self.assertIsNotNone(facebook_match)
        facebook_id = facebook_match.group(1).decode("ascii") if facebook_match else ""

        export_response = self.client.post(
            "/exportar",
            data={
                "network": "facebook",
                "facebook_upload_id": facebook_id,
                "facebook_filename": "facebook.csv",
                "facebook_hashtag": "#OPORTUNIDAD",
            },
        )

        self.assertEqual(export_response.status_code, 200)
        self.assertIn("facebook_resumen.csv", export_response.headers["Content-Disposition"])
        exported = csv.DictReader(
            io.StringIO(export_response.data.decode("utf-8-sig"), newline="")
        )
        self.assertEqual(
            exported.fieldnames,
            [
                "RedSocial",
                "TipoHashtag",
                "HoraDePublicacion",
                "Enlace",
                "Alcance",
                "MeGustas",
            ],
        )
        rows: list[dict[str, Any]] = list(exported)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0],
            {
                "RedSocial": "Facebook",
                "TipoHashtag": "#oportunidad",
                "HoraDePublicacion": "2026-08-01 10:00:00",
                "Enlace": "https://example.com/oportunidad",
                "Alcance": "42",
                "MeGustas": "9",
            },
        )

    def test_rejects_csv_selected_for_the_wrong_network(self) -> None:
        instagram_csv, _facebook_csv = self._both_network_csvs()
        response = self.client.post(
            "/analizar",
            data={"facebook_csv": (io.BytesIO(instagram_csv), "instagram.csv")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"no parece ser un CSV de Facebook", response.data)
        self.assertIn(b"Selecciona el CSV de Instagram", response.data)

    def test_rejects_non_csv_upload(self) -> None:
        response = self.client.post(
            "/analizar",
            data={"instagram_csv": (io.BytesIO(b"not a csv"), "reporte.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"extensi\xc3\xb3n .csv", response.data)


if __name__ == "__main__":
    unittest.main()
