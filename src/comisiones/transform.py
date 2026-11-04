"""Transformación: limpieza, validaciones de calidad y Join por empleado_id."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

log = logging.getLogger(__name__)

MAPEO_COLUMNAS_CSV = {
    "empleado_id": "empleado_id",
    "nombre y apellido": "nombre_apellido_csv",
    "comisión": "mnt_comision",
    "comision": "mnt_comision",
}


class ErrorCalidadDatos(ValueError):
    """Se lanza cuando los datos de entrada no cumplen las reglas mínimas."""


@dataclass
class ReporteCalidad:
    filas_empleados: int = 0
    filas_comisiones: int = 0
    filas_salida: int = 0
    empleados_con_comision: int = 0
    empleados_sin_comision: list[int] = field(default_factory=list)
    comisiones_sin_empleado: list[int] = field(default_factory=list)
    comisiones_sobre_tope: list[int] = field(default_factory=list)
    total_salario: float = 0.0
    total_comision: float = 0.0
    total_salario_total: float = 0.0

    def como_dict(self) -> dict:
        return self.__dict__.copy()


def periodo_desde_nombre(nombre_archivo: str) -> str | None:
    """Obtiene el periodo AAAAMM del nombre del archivo (p. ej. ..._V1_202610.csv)."""
    m = re.search(r"_(\d{6})(?:_\d+)?\.csv$", nombre_archivo, flags=re.IGNORECASE)
    return m.group(1) if m else None


def limpiar_comisiones(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza nombres de columnas y tipos del CSV de comisiones."""
    renombrar = {}
    for col in df.columns:
        clave = col.strip().lower()
        if clave in MAPEO_COLUMNAS_CSV:
            renombrar[col] = MAPEO_COLUMNAS_CSV[clave]
    df = df.rename(columns=renombrar)

    faltantes = {"empleado_id", "mnt_comision"} - set(df.columns)
    if faltantes:
        raise ErrorCalidadDatos(f"El CSV de comisiones no tiene las columnas: {sorted(faltantes)}")

    df = df.dropna(how="all").copy()
    df["empleado_id"] = pd.to_numeric(df["empleado_id"].str.strip(), errors="coerce")
    # Admite "9000", "9000.50" y "9.000,50"
    comision = df["mnt_comision"].astype(str).str.strip()
    comision = comision.where(~comision.str.contains(","), comision.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    df["mnt_comision"] = pd.to_numeric(comision, errors="coerce")

    invalidas = df[df["empleado_id"].isna() | df["mnt_comision"].isna()]
    if not invalidas.empty:
        raise ErrorCalidadDatos(f"Filas con empleado_id o comisión no numérica: {invalidas.index.tolist()}")
    if (df["mnt_comision"] < 0).any():
        raise ErrorCalidadDatos("Existen comisiones negativas en el CSV")

    duplicados = df[df["empleado_id"].duplicated(keep=False)]["empleado_id"].unique().tolist()
    if duplicados:
        raise ErrorCalidadDatos(f"empleado_id duplicados en el CSV: {sorted(int(x) for x in duplicados)}")

    df["empleado_id"] = df["empleado_id"].astype("int64")
    if "nombre_apellido_csv" in df.columns:
        df["nombre_apellido_csv"] = (
            df["nombre_apellido_csv"].str.replace(r"\s*,\s*", " ", regex=True).str.strip()
        )
    return df


def limpiar_empleados(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    for col in ("empleado_id", "mnt_salario"):
        if col not in df.columns:
            raise ErrorCalidadDatos(f"La tabla de empleados no tiene la columna '{col}'")
    df["empleado_id"] = pd.to_numeric(df["empleado_id"], errors="raise").astype("int64")
    df["mnt_salario"] = pd.to_numeric(df["mnt_salario"], errors="raise").astype("float64")
    if "mnt_tope_comision" in df.columns:
        df["mnt_tope_comision"] = pd.to_numeric(df["mnt_tope_comision"], errors="coerce")
    if df["empleado_id"].duplicated().any():
        raise ErrorCalidadDatos("empleado_id duplicado en la tabla de empleados")
    return df


def calcular_salario_total(
    empleados: pd.DataFrame,
    comisiones: pd.DataFrame,
    periodo: str | None = None,
    entorno: str = "dev",
) -> tuple[pd.DataFrame, ReporteCalidad]:
    """Join empleado ⟕ comisión por empleado_id y cálculo de salario_total.

    Regla de negocio: ``salario_total = mnt_salario + mnt_comision``.
    Se usa LEFT JOIN desde empleados para no perder a ningún trabajador; quien no
    figura en el CSV recibe comisión 0 y queda marcado con ``tiene_comision=False``.
    """
    emp = limpiar_empleados(empleados)
    com = limpiar_comisiones(comisiones)

    df = emp.merge(com, on="empleado_id", how="left", validate="one_to_one", indicator=True)
    df["tiene_comision"] = df["_merge"].eq("both")
    df = df.drop(columns="_merge")
    df["mnt_comision"] = df["mnt_comision"].fillna(0.0).astype("float64")
    df["salario_total"] = (df["mnt_salario"] + df["mnt_comision"]).round(2)

    if "mnt_tope_comision" in df.columns:
        df["supera_tope_comision"] = df["mnt_tope_comision"].notna() & (df["mnt_comision"] > df["mnt_tope_comision"])
    else:
        df["supera_tope_comision"] = False

    if {"nom_empleado", "ape_empleado"} <= set(df.columns):
        df["nombre_completo"] = (df["nom_empleado"].astype(str).str.strip() + " " + df["ape_empleado"].astype(str).str.strip())

    df["periodo"] = periodo
    df["entorno"] = entorno
    df["fecha_proceso"] = datetime.now(timezone.utc).replace(microsecond=0)

    orden = [c for c in [
        "empleado_id", "tip_documento", "num_documento", "nombre_completo", "nom_empleado", "ape_empleado",
        "cod_cargo", "cod_departamento", "mnt_salario", "mnt_comision", "salario_total",
        "mnt_tope_comision", "tiene_comision", "supera_tope_comision", "periodo", "entorno", "fecha_proceso",
    ] if c in df.columns]
    df = df[orden].sort_values("empleado_id").reset_index(drop=True)

    huerfanas = sorted(set(com["empleado_id"]) - set(emp["empleado_id"]))
    rep = ReporteCalidad(
        filas_empleados=len(emp),
        filas_comisiones=len(com),
        filas_salida=len(df),
        empleados_con_comision=int(df["tiene_comision"].sum()),
        empleados_sin_comision=df.loc[~df["tiene_comision"], "empleado_id"].astype(int).tolist(),
        comisiones_sin_empleado=[int(x) for x in huerfanas],
        comisiones_sobre_tope=df.loc[df["supera_tope_comision"], "empleado_id"].astype(int).tolist(),
        total_salario=round(float(df["mnt_salario"].sum()), 2),
        total_comision=round(float(df["mnt_comision"].sum()), 2),
        total_salario_total=round(float(df["salario_total"].sum()), 2),
    )
    if huerfanas:
        log.warning("Comisiones sin empleado en la tabla: %s", huerfanas)
    log.info("Join completado: %s", rep.como_dict())
    return df, rep
