"""Extracción: tabla dmc.rrhh.empleado (PostgreSQL) y CSV de comisiones (Blob Storage)."""
from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd

from .config import PostgresConfig, StorageConfig

log = logging.getLogger(__name__)

COLUMNAS_EMPLEADO = [
    "empleado_id",
    "tip_documento",
    "num_documento",
    "nom_empleado",
    "ape_empleado",
    "cod_cargo",
    "cod_departamento",
    "mnt_salario",
    "mnt_tope_comision",
]

SQL_EMPLEADO = """
SELECT empleado_id, tip_documento, num_documento, nom_empleado, ape_empleado,
       cod_cargo, cod_departamento, mnt_salario, mnt_tope_comision
FROM {schema}.{table}
"""


# --------------------------------------------------------------------------- #
# PostgreSQL
# --------------------------------------------------------------------------- #
def extraer_empleados_postgres(cfg: PostgresConfig) -> pd.DataFrame:
    """Lee la tabla de empleados desde PostgreSQL (solo lectura)."""
    from sqlalchemy import create_engine, text  # import diferido: no es necesario en tests

    sql = SQL_EMPLEADO.format(schema=cfg.schema, table=cfg.table)
    log.info("Conectando a PostgreSQL %s:%s/%s (schema=%s)", cfg.host, cfg.port, cfg.database, cfg.schema)
    engine = create_engine(cfg.url, pool_pre_ping=True)
    with engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    log.info("Empleados extraídos de PostgreSQL: %d filas", len(df))
    return df


def extraer_empleados_archivo(ruta: str | Path) -> pd.DataFrame:
    """Lee empleados desde un CSV exportado (uso en pruebas / ejecución offline)."""
    df = pd.read_csv(ruta, sep=None, engine="python", encoding="utf-8-sig")
    log.info("Empleados leídos de archivo %s: %d filas", ruta, len(df))
    return df


# --------------------------------------------------------------------------- #
# CSV de comisiones
# --------------------------------------------------------------------------- #
def leer_csv_comisiones(contenido: bytes | str | Path) -> pd.DataFrame:
    """Parsea el CSV de comisiones.

    Formato observado: separador ';', UTF-8, fin de línea CRLF y cabecera
    ``empleado_id;Nombre y Apellido;Comisión``. El nombre viene como
    "Nombre, Apellido" (la coma es parte del texto, no un separador).
    """
    if isinstance(contenido, (bytes, bytearray)):
        buffer = io.StringIO(contenido.decode("utf-8-sig"))
    elif isinstance(contenido, Path) or (isinstance(contenido, str) and Path(contenido).exists()):
        buffer = Path(contenido).read_text(encoding="utf-8-sig")
        buffer = io.StringIO(buffer)
    else:
        buffer = io.StringIO(str(contenido))

    df = pd.read_csv(buffer, sep=";", dtype=str, skip_blank_lines=True)
    df.columns = [c.strip() for c in df.columns]
    log.info("CSV de comisiones leído: %d filas, columnas=%s", len(df), list(df.columns))
    return df


def descargar_csv_blob(cfg: StorageConfig) -> bytes:
    """Descarga el CSV de comisiones desde Azure Blob Storage."""
    from azure.storage.blob import BlobServiceClient

    if cfg.connection_string:
        cliente = BlobServiceClient.from_connection_string(cfg.connection_string)
    else:
        from azure.identity import DefaultAzureCredential

        cliente = BlobServiceClient(
            account_url=f"https://{cfg.account_name}.blob.core.windows.net",
            credential=cfg.account_key or DefaultAzureCredential(),
        )
    blob = cliente.get_blob_client(container=cfg.raw_container, blob=cfg.csv_blob)
    log.info("Descargando blob %s/%s", cfg.raw_container, cfg.csv_blob)
    return blob.download_blob().readall()
