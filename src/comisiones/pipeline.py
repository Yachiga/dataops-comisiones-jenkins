"""Orquestador del flujo de comisiones.

Ejemplos:
    # Azure: PostgreSQL -> Blob (CSV) -> Join -> Parquet en ADLS Gen2
    python -m comisiones.pipeline --entorno prod --modo azure

    # Local: PostgreSQL real + CSV local -> salida en ./output
    python -m comisiones.pipeline --modo local --csv data/input/ComisionEmpleados_V1_202610.csv

    # Offline (CI): fixture de empleados + CSV local
    python -m comisiones.pipeline --modo local --empleados-file tests/fixtures/empleados_fixture.csv \
        --csv data/input/ComisionEmpleados_V1_202610.csv
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import extract, load, transform
from .config import cargar_config

log = logging.getLogger("comisiones")


def configurar_logs(nivel: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, nivel.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def ejecutar(args: argparse.Namespace) -> dict:
    inicio = time.perf_counter()
    usa_postgres = args.empleados_file is None
    cfg = cargar_config(args.entorno, requiere_postgres=usa_postgres)
    log.info("=== Inicio pipeline comisiones | entorno=%s | modo=%s ===", cfg.entorno, args.modo)

    # 1) Extracción de empleados
    if usa_postgres:
        empleados = extract.extraer_empleados_postgres(cfg.postgres)
    else:
        empleados = extract.extraer_empleados_archivo(args.empleados_file)

    # 2) Extracción del CSV de comisiones
    if args.modo == "azure":
        contenido = extract.descargar_csv_blob(cfg.storage)
        nombre_csv = cfg.storage.csv_blob
    else:
        contenido = Path(args.csv)
        nombre_csv = Path(args.csv).name
    comisiones = extract.leer_csv_comisiones(contenido)
    periodo = args.periodo or transform.periodo_desde_nombre(nombre_csv)

    # 3) Transformación + Join
    consolidado, reporte = transform.calcular_salario_total(empleados, comisiones, periodo=periodo, entorno=cfg.entorno)

    # 4) Carga
    if args.modo == "azure":
        destino = load.subir_parquet_datalake(consolidado, cfg.storage, periodo)
        salidas = [destino]
    else:
        rutas = load.guardar_local(consolidado, args.salida, f"salario_total_{periodo or 'sin_periodo'}", args.formatos)
        salidas = [str(r) for r in rutas]

    resultado = {
        "estado": "Succeeded",
        "entorno": cfg.entorno,
        "modo": args.modo,
        "periodo": periodo,
        "salidas": salidas,
        "calidad": reporte.como_dict(),
        "duracion_seg": round(time.perf_counter() - inicio, 3),
    }
    if args.modo == "local":
        Path(args.salida).mkdir(parents=True, exist_ok=True)
        (Path(args.salida) / "reporte_ejecucion.json").write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("=== Fin pipeline: %s ===", json.dumps(resultado, ensure_ascii=False))
    return resultado


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pipeline DataOps de comisiones de empleados")
    p.add_argument("--entorno", choices=["dev", "test", "prod"], default=None, help="Por defecto PIPELINE_ENV o dev")
    p.add_argument("--modo", choices=["azure", "local"], default="local")
    p.add_argument("--csv", default="data/input/ComisionEmpleados_V1_202610.csv", help="CSV local (modo local)")
    p.add_argument("--empleados-file", default=None, help="CSV de empleados en lugar de PostgreSQL (pruebas)")
    p.add_argument("--periodo", default=None, help="AAAAMM; por defecto se toma del nombre del CSV")
    p.add_argument("--salida", default="output", help="Carpeta de salida (modo local)")
    p.add_argument("--formatos", nargs="+", default=["parquet", "xlsx", "csv"])
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    configurar_logs(args.log_level)
    try:
        ejecutar(args)
        return 0
    except transform.ErrorCalidadDatos as exc:
        log.error("Validación de calidad fallida: %s", exc)
        return 2
    except Exception:  # noqa: BLE001
        log.exception("El pipeline terminó con error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
