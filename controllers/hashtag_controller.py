import csv
import io
import re
import time
import uuid
from pathlib import Path

from flask import Blueprint, Response, current_app, render_template, request
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import RequestEntityTooLarge

from models.hashtag_model import NetworkDashboard, get_dashboard_data

hashtag_blueprint = Blueprint("hashtags", __name__)
UPLOAD_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
UPLOAD_EXPIRATION_SECONDS = 24 * 60 * 60
NETWORKS = {
    "instagram": {"label": "Instagram", "field": "instagram_csv"},
    "facebook": {"label": "Facebook", "field": "facebook_csv"},
}


def _render_page(
    dashboards: dict[str, NetworkDashboard] | None = None,
    upload_ids: dict[str, str] | None = None,
    filenames: dict[str, str] | None = None,
    filters: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
    error: str | None = None,
    status: int = 200,
):
    dashboards = dashboards or {}
    upload_ids = upload_ids or {}
    filenames = filenames or {}
    filters = filters or {}
    errors = errors or {}
    network_views = [
        {
            "key": key,
            "label": network["label"],
            "dashboard": dashboards.get(key),
            "upload_id": upload_ids.get(key, ""),
            "filename": filenames.get(key, ""),
            "hashtag": filters.get(key, ""),
            "error": errors.get(key),
        }
        for key, network in NETWORKS.items()
    ]
    return (
        render_template(
            "index.html",
            networks=network_views,
            error=error,
            max_upload_mb=current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
        ),
        status,
    )


def _upload_directory() -> Path:
    directory = Path(current_app.config["UPLOAD_FOLDER"])
    directory.mkdir(parents=True, exist_ok=True)
    expiration_time = time.time() - UPLOAD_EXPIRATION_SECONDS
    for saved_file in directory.glob("*.csv"):
        try:
            if saved_file.stat().st_mtime < expiration_time:
                saved_file.unlink()
        except FileNotFoundError:
            continue
    return directory


def _saved_upload(upload_id: str) -> Path | None:
    if not UPLOAD_ID_PATTERN.fullmatch(upload_id):
        return None
    path = Path(current_app.config["UPLOAD_FOLDER"]) / f"{upload_id}.csv"
    return path if path.is_file() else None


def _display_filename(filename: str) -> str:
    return Path(filename.replace("\\", "/")).name or "publicaciones.csv"


def _read_dashboard(
    upload_id: str,
    filename: str,
    network: str,
    hashtag_filter: str,
) -> NetworkDashboard:
    path = _saved_upload(upload_id)
    if path is None:
        raise ValueError(
            "El archivo temporal ya no está disponible. Selecciona el CSV otra vez."
        )
    dashboard = get_dashboard_data(path.read_bytes(), filename, hashtag_filter)
    expected_network = NETWORKS[network]["label"]
    if dashboard["network"] != expected_network:
        raise ValueError(f"El archivo seleccionado no parece ser un CSV de {expected_network}.")
    return dashboard


def _store_upload(
    uploaded_file: FileStorage, network: str, hashtag_filter: str
) -> tuple[str, str, NetworkDashboard]:
    filename = _display_filename(uploaded_file.filename or "")
    if Path(filename).suffix.casefold() != ".csv":
        raise ValueError("El archivo seleccionado debe tener extensión .csv.")

    upload_id = uuid.uuid4().hex
    path = _upload_directory() / f"{upload_id}.csv"
    try:
        uploaded_file.save(path)
        dashboard = _read_dashboard(upload_id, filename, network, hashtag_filter)
    except (OSError, ValueError, csv.Error):
        path.unlink(missing_ok=True)
        raise
    return upload_id, filename, dashboard


@hashtag_blueprint.get("/")
def index():
    """Muestra las áreas independientes para seleccionar cada CSV."""
    return _render_page()


@hashtag_blueprint.post("/analizar")
def analyze_csv():
    """Carga uno o ambos CSV y conserva las selecciones de la otra red."""
    _upload_directory()
    upload_ids: dict[str, str] = {}
    filenames: dict[str, str] = {}
    filters: dict[str, str] = {}
    dashboards: dict[str, NetworkDashboard] = {}
    errors: dict[str, str] = {}
    uploaded_any_file = False

    for network, settings in NETWORKS.items():
        uploaded_file = request.files.get(settings["field"])
        if uploaded_file is not None and uploaded_file.filename:
            uploaded_any_file = True
            try:
                hashtag = request.form.get(f"{network}_hashtag", "")
                upload_id, filename, dashboard = _store_upload(
                    uploaded_file, network, hashtag
                )
            except (OSError, ValueError, csv.Error) as error:
                errors[network] = str(error)
                continue
            upload_ids[network] = upload_id
            filenames[network] = filename
            filters[network] = hashtag
            dashboards[network] = dashboard
            continue
        else:
            upload_id = request.form.get(f"{network}_upload_id", "")
            filename = _display_filename(
                request.form.get(f"{network}_filename", "publicaciones.csv")
            )
            filters[network] = request.form.get(f"{network}_hashtag", "")

        if not upload_id:
            continue
        upload_ids[network] = upload_id
        filenames[network] = filename
        try:
            dashboards[network] = _read_dashboard(
                upload_id, filename, network, filters[network]
            )
        except (OSError, ValueError, csv.Error) as error:
            errors[network] = str(error)
            upload_ids.pop(network, None)
            filenames.pop(network, None)
            filters.pop(network, None)

    if not uploaded_any_file and not upload_ids:
        return _render_page(
            error="Selecciona el archivo CSV de Instagram, Facebook o ambos.",
            status=400,
        )
    return _render_page(dashboards, upload_ids, filenames, filters, errors)


@hashtag_blueprint.post("/filtrar")
def filter_csv():
    """Aplica el hashtag elegido a una red y conserva la otra tabla."""
    network = request.form.get("network", "")
    if network not in NETWORKS:
        return _render_page(error="Selecciona una red social válida.", status=400)

    upload_ids: dict[str, str] = {}
    filenames: dict[str, str] = {}
    filters: dict[str, str] = {}
    dashboards: dict[str, NetworkDashboard] = {}
    errors: dict[str, str] = {}

    for key in NETWORKS:
        upload_id = request.form.get(f"{key}_upload_id", "")
        if not upload_id:
            continue
        filename = _display_filename(
            request.form.get(f"{key}_filename", "publicaciones.csv")
        )
        hashtag = (
            request.form.get("hashtag", "")
            if key == network
            else request.form.get(f"{key}_hashtag", "")
        )
        upload_ids[key] = upload_id
        filenames[key] = filename
        filters[key] = hashtag
        try:
            dashboards[key] = _read_dashboard(upload_id, filename, key, hashtag)
        except (OSError, ValueError, csv.Error) as error:
            errors[key] = str(error)
            upload_ids.pop(key, None)
            filenames.pop(key, None)
            filters.pop(key, None)
    return _render_page(dashboards, upload_ids, filenames, filters, errors)


@hashtag_blueprint.post("/exportar")
def export_filtered_csv():
    """Descarga las filas filtradas de la red seleccionada."""
    network = request.form.get("network", "")
    if network not in NETWORKS:
        return _render_page(error="Selecciona una red social válida.", status=400)

    upload_id = request.form.get(f"{network}_upload_id", "")
    filename = _display_filename(
        request.form.get(f"{network}_filename", "publicaciones.csv")
    )
    hashtag_filter = request.form.get(f"{network}_hashtag", "")
    try:
        dashboard = _read_dashboard(upload_id, filename, network, hashtag_filter)
    except (OSError, ValueError, csv.Error) as error:
        return _render_page(errors={network: str(error)}, status=400)

    output = io.StringIO(newline="")
    export_headers = [
        "RedSocial",
        "TipoHashtag",
        "HoraDePublicacion",
        "Enlace",
        "Alcance",
        "MeGustas",
    ]
    writer = csv.DictWriter(output, fieldnames=export_headers)
    writer.writeheader()
    for post in dashboard["posts"]:
        matching_hashtag = next(
            (
                hashtag
                for hashtag in post["hashtags"]
                if hashtag.lstrip("#").casefold()
                == hashtag_filter.strip().lstrip("#").casefold()
            ),
            post["category"],
        )
        writer.writerow(
            {
                "RedSocial": dashboard["network"],
                "TipoHashtag": matching_hashtag,
                "HoraDePublicacion": post["published_at"] or "",
                "Enlace": post["permalink"] or "",
                "Alcance": post["reach"] if post["reach"] is not None else "",
                "MeGustas": post["likes"] if post["likes"] is not None else "",
            }
        )
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{network}_resumen.csv"'
        },
    )


@hashtag_blueprint.app_errorhandler(RequestEntityTooLarge)
def upload_too_large(_error):
    return _render_page(
        error=(
            "El archivo supera el límite de "
            f"{current_app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB."
        ),
        status=413,
    )
