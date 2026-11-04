"""Carga: escritura del consolidado en Parquet (Data Lake) y Excel opcional."""
from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd

from .config import StorageConfig

log = logging.getLogger(__name__)


def a_parquet_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.to_parquet(buffer, engine="pyarrow", index=False, compression="snappy")
    return buffer.getvalue()


def guardar_local(df: pd.DataFrame, carpeta: str | Path, nombre_base: str, formatos=("parquet", "xlsx", "csv")) -> list[Path]:
    """Guarda el consolidado en disco. Devuelve las rutas generadas."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas: list[Path] = []
    salida = df.copy()
    if "fecha_proceso" in salida.columns:
        salida["fecha_proceso"] = salida["fecha_proceso"].dt.tz_localize(None)

    for fmt in formatos:
        ruta = carpeta / f"{nombre_base}.{fmt}"
        if fmt == "parquet":
            try:
                salida.to_parquet(ruta, engine="pyarrow", index=False, compression="snappy")
            except ImportError:
                log.warning("pyarrow no está instalado: se omite la salida Parquet local")
                continue
        elif fmt == "xlsx":
            salida.to_excel(ruta, index=False, sheet_name="salario_total")
        elif fmt == "csv":
            salida.to_csv(ruta, index=False, sep=";", encoding="utf-8-sig")
        else:
            raise ValueError(f"Formato no soportado: {fmt}")
        log.info("Archivo generado: %s", ruta)
        rutas.append(ruta)
    return rutas


def subir_parquet_datalake(df: pd.DataFrame, cfg: StorageConfig, periodo: str | None) -> str:
    """Escribe el Parquet en ADLS Gen2: curated/<output_dir>/periodo=AAAAMM/salario_total.parquet"""
    from azure.storage.filedatalake import DataLakeServiceClient

    if cfg.connection_string:
        servicio = DataLakeServiceClient.from_connection_string(cfg.connection_string)
    else:
        from azure.identity import DefaultAzureCredential

        servicio = DataLakeServiceClient(
            account_url=f"https://{cfg.account_name}.dfs.core.windows.net",
            credential=cfg.account_key or DefaultAzureCredential(),
        )
    salida = df.copy()
    if "fecha_proceso" in salida.columns:
        salida["fecha_proceso"] = salida["fecha_proceso"].dt.tz_localize(None)

    ruta = f"{cfg.output_dir}/periodo={periodo or 'sin_periodo'}/salario_total.parquet"
    fs = servicio.get_file_system_client(cfg.curated_container)
    archivo = fs.get_file_client(ruta)
    archivo.upload_data(a_parquet_bytes(salida), overwrite=True)
    destino = f"abfss://{cfg.curated_container}@{cfg.account_name}.dfs.core.windows.net/{ruta}"
    log.info("Parquet escrito en Data Lake: %s", destino)
    return destino
