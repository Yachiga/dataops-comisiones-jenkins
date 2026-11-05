"""Verifica el Parquet consolidado de salario_total.

Dos modos:
  * Data Lake de Azure:  --account <storage> --periodo AAAAMM   (usado por deploy.sh)
  * Carpeta local:       --ruta datalake/dev                       (usado por GitHub Actions / Jenkins)

Reglas: salario_total = mnt_salario + mnt_comision en todas las filas, sin
empleado_id duplicado y la comisión total del Join no supera la del CSV.
"""
import argparse
import io
import os
import sys
from pathlib import Path

import pandas as pd


def leer_azure(cuenta: str, periodo: str) -> pd.DataFrame:
    from azure.identity import DefaultAzureCredential
    from azure.storage.filedatalake import DataLakeServiceClient

    credencial = os.getenv("AZURE_STORAGE_KEY") or DefaultAzureCredential()
    svc = DataLakeServiceClient(f"https://{cuenta}.dfs.core.windows.net", credential=credencial)
    fs = svc.get_file_system_client("curated")
    carpeta = f"comisiones/salario_total/periodo={periodo}"
    archivos = [p.name for p in fs.get_paths(carpeta) if p.name.endswith(".parquet")]
    print("Archivos Parquet:", archivos)
    if not archivos:
        sys.exit("ERROR: no se encontró Parquet en " + carpeta)
    return pd.concat(pd.read_parquet(io.BytesIO(fs.get_file_client(f).download_file().readall())) for f in archivos)


def leer_local(ruta: str) -> pd.DataFrame:
    archivos = sorted(Path(ruta).glob("*.parquet"))
    print("Archivos Parquet:", [str(a) for a in archivos])
    if not archivos:
        sys.exit("ERROR: no se encontró Parquet en " + ruta)
    return pd.concat(pd.read_parquet(a) for a in archivos)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account")
    ap.add_argument("--periodo")
    ap.add_argument("--ruta")
    ap.add_argument("--csv", required=True, help="CSV original para cuadrar el total de comisiones")
    ap.add_argument("--resumen", help="Archivo Markdown donde anexar el resumen (GITHUB_STEP_SUMMARY)")
    ap.add_argument("--entorno", default="")
    a = ap.parse_args()

    df = leer_local(a.ruta) if a.ruta else leer_azure(a.account, a.periodo)
    cols = ["empleado_id", "nombre_completo", "mnt_salario", "mnt_comision", "salario_total", "tiene_comision"]
    print(df[[c for c in cols if c in df.columns]].head(10).to_string(index=False))

    csv = pd.read_csv(a.csv, sep=";", dtype=str)
    total_csv = pd.to_numeric(csv["Comisión"]).sum()
    salario = df["mnt_salario"].astype(float)
    comision = df["mnt_comision"].astype(float)
    total = df["salario_total"].astype(float)

    errores = []
    if (total.round(2) != (salario + comision).round(2)).any():
        errores.append("salario_total != mnt_salario + mnt_comision")
    if df["empleado_id"].duplicated().any():
        errores.append("empleado_id duplicado en la salida")
    total_join = comision[df["tiene_comision"].astype(bool)].sum()
    if total_join > total_csv + 0.01:
        errores.append("La comisión total del Join supera la del CSV")

    resumen = {
        "Filas (empleados)": len(df),
        "Empleados con comisión": int(df["tiene_comision"].astype(bool).sum()),
        "Σ salario": f"{salario.sum():,.2f}",
        "Σ comisión (Join)": f"{total_join:,.2f}",
        "Σ comisión (CSV)": f"{total_csv:,.2f}",
        "Σ salario_total": f"{total.sum():,.2f}",
        "Resultado": "OK" if not errores else "; ".join(errores),
    }
    for k, v in resumen.items():
        print(f"{k}: {v}")

    if a.resumen:
        with open(a.resumen, "a", encoding="utf-8") as f:
            f.write(f"## Parquet salario_total {a.entorno}\n\n| Indicador | Valor |\n|---|---|\n")
            f.writelines(f"| {k} | {v} |\n" for k, v in resumen.items())
            f.write("\n### Primeras filas\n\n")
            f.write(df[[c for c in cols if c in df.columns]].head(10).to_markdown(index=False))
            f.write("\n")

    if errores:
        sys.exit("ERROR: " + "; ".join(errores))
    print("OK: Parquet validado")


if __name__ == "__main__":
    main()
