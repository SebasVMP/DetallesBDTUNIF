from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime
from typing import TypedDict

CATEGORY_PATTERN = re.compile(r"(?<!\w)#[\w]+", re.UNICODE)
EMPTY_METRICS = {"", "-", "—", "n/a", "na", "null"}


class Post(TypedDict):
    category: str
    hashtags: list[str]
    published_at: str | None
    sort_date: datetime | None
    permalink: str | None
    link_url: str | None
    reach: int | None
    likes: int | None
    source_row: dict[str, str]


class NetworkDashboard(TypedDict):
    filename: str
    network: str
    posts: list[Post]
    hashtags: list[str]
    hashtag_filter: str
    filtered_rows: list[dict[str, str]]
    csv_headers: list[str]
    post_count: int
    category_count: int
    reach_total: int
    reach_reported: int
    likes_total: int
    likes_reported: int


def _normalize_label(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]", "", without_accents)


def _find_header(headers: list[str], *aliases: str) -> str | None:
    normalized_aliases = {_normalize_label(alias) for alias in aliases}
    return next(
        (header for header in headers if _normalize_label(header) in normalized_aliases),
        None,
    )


def _parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value or value.casefold() == "total":
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        pass

    for date_format in (
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    return None


def _to_int(value: str, field: str, row_number: int) -> int | None:
    normalized = value.strip().replace(",", "")
    if normalized.casefold() in EMPTY_METRICS:
        return None
    try:
        return int(normalized)
    except ValueError as error:
        raise ValueError(
            f"El valor {value!r} de la columna {field} no es un entero "
            f"válido (registro {row_number})."
        ) from error


def _read_csv(csv_content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = csv_content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(
            "No se pudo leer el archivo como UTF-8. Exporta el CSV con codificación UTF-8."
        ) from error

    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = reader.fieldnames
    if not headers or any(not header.strip() for header in headers):
        raise ValueError("El CSV no tiene una fila de encabezados válida.")
    normalized_headers = [_normalize_label(header) for header in headers]
    if len(normalized_headers) != len(set(normalized_headers)):
        raise ValueError("El CSV contiene nombres de columnas duplicados.")

    rows: list[dict[str, str]] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(
                f"El registro {row_number} tiene más valores que columnas."
            )
        if any(value is None for value in row.values()):
            raise ValueError(
                f"El registro {row_number} tiene menos valores que columnas."
            )
        if not any(value and value.strip() for value in row.values()):
            continue
        rows.append({header: row[header] or "" for header in headers})

    if not rows:
        raise ValueError("El CSV no contiene publicaciones para analizar.")
    return headers, rows


def _extract_hashtags(row: dict[str, str], text_fields: list[str]) -> list[str]:
    hashtags: dict[str, None] = {}
    for field in text_fields:
        for match in CATEGORY_PATTERN.finditer(row.get(field, "")):
            hashtags.setdefault(match.group(0).casefold(), None)
    return list(hashtags)


def get_dashboard_data(
    csv_content: bytes,
    filename: str,
    hashtag_filter: str = "",
) -> NetworkDashboard:
    """Lee un CSV de publicaciones y prepara sus métricas y filas filtradas."""
    headers, rows = _read_csv(csv_content)
    title_field = _find_header(headers, "Título", "Title")
    description_field = _find_header(headers, "Descripción", "Description")
    custom_tags_field = _find_header(
        headers, "Etiquetas personalizadas", "Custom labels"
    )
    text_fields = [
        field
        for field in (title_field, description_field, custom_tags_field)
        if field is not None
    ]

    publication_time_field = _find_header(
        headers, "Hora de publicación", "Publication time", "Published at"
    )
    date_field = _find_header(headers, "Fecha", "Date")
    date_fields = [
        field
        for field in (publication_time_field, date_field)
        if field is not None
    ]
    permalink_field = _find_header(headers, "Enlace permanente", "Permalink")
    reach_field = _find_header(headers, "Alcance", "Reach")
    likes_field = _find_header(headers, "Me gusta", "Likes")
    if likes_field is None:
        likes_field = _find_header(headers, "Reacciones", "Reactions")

    normalized_headers = {_normalize_label(header) for header in headers}
    if "nombredeusuariodelacuenta" in normalized_headers:
        network = "Instagram"
    elif (
        "nombredelapagina" in normalized_headers
        or "reacciones" in normalized_headers
    ):
        network = "Facebook"
    else:
        network = "CSV"

    normalized_filter = hashtag_filter.strip().lstrip("#").casefold()
    all_hashtags: dict[str, None] = {}
    matching_posts: list[Post] = []

    for row_number, row in enumerate(rows, start=2):
        hashtags = _extract_hashtags(row, text_fields)
        for hashtag in hashtags:
            all_hashtags.setdefault(hashtag, None)
        if normalized_filter and not any(
            hashtag.lstrip("#").casefold() == normalized_filter
            for hashtag in hashtags
        ):
            continue

        published_at = None
        sort_date = None
        for field in date_fields:
            value = row[field].strip()
            if value and value.casefold() != "total":
                published_at = value
                sort_date = _parse_datetime(value)
                break

        permalink = row.get(permalink_field, "").strip() if permalink_field else ""
        link_url = (
            permalink
            if permalink.startswith(("https://", "http://"))
            else None
        )
        category = hashtags[0] if hashtags else "Sin hashtag"
        matching_posts.append(
            {
                "category": category,
                "hashtags": hashtags,
                "published_at": published_at,
                "sort_date": sort_date,
                "permalink": permalink or None,
                "link_url": link_url,
                "reach": (
                    _to_int(row[reach_field], reach_field, row_number)
                    if reach_field
                    else None
                ),
                "likes": (
                    _to_int(row[likes_field], likes_field, row_number)
                    if likes_field
                    else None
                ),
                "source_row": row,
            }
        )

    display_posts = sorted(
        matching_posts,
        key=lambda post: post["sort_date"] or datetime.min,
        reverse=True,
    )
    reach_values = [post["reach"] for post in matching_posts if post["reach"] is not None]
    like_values = [post["likes"] for post in matching_posts if post["likes"] is not None]

    return {
        "filename": filename,
        "network": network,
        "posts": display_posts,
        "hashtags": sorted(all_hashtags),
        "hashtag_filter": hashtag_filter.strip(),
        "filtered_rows": [post["source_row"] for post in matching_posts],
        "csv_headers": headers,
        "post_count": len(matching_posts),
        "category_count": len({post["category"] for post in matching_posts}),
        "reach_total": sum(reach_values),
        "reach_reported": len(reach_values),
        "likes_total": sum(like_values),
        "likes_reported": len(like_values),
    }
