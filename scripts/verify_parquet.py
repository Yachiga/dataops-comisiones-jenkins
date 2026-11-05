"""Descarga el Parquet de curated y verifica reglas básicas (usado en CD)."""
import argparse
import io
import os
import sys

import pandas as pd
from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import DataLakeServiceClient

ap = argparse.ArgumentParser()
ap.add_argument("--account", required=True)
ap.add_argument("--periodo", required=True)
ap.add_argument("--csv", required=True, help="CSV original para cuadrar el total de comisiones")
a = ap.parse_args()

credencial = os.getenv("AZURE_STORAGE_KEY") or DefaultAzureCredential()
svc = DataLakeServiceClient(f"https://{a.account}.dfs.core.windows.net", credential=credencial)
fs = svc.get_file_system_client("curated")
carpeta = f"comisiones/salario_total/periodo={a.periodo}"
archivos = [p.name for p in fs.get_paths(carpeta) if p.name.endswith(".parquet")]
print("Archivos Parquet:", archivos)
if not archivos:
    sys.exit("ERROR: no se encontró Parquet en " + carpeta)

df = pd.concat(pd.read_parquet(io.BytesIO(fs.get_file_client(f).download_file().readall())) for f in archivos)
print(df.head(10).to_string(index=False))
csv = pd.read_csv(a.csv, sep=";", dtype=str)
total_csv = pd.to_numeric(csv["Comisión"]).sum()

errores = []
if (df["salario_total"].astype(float).round(2) != (df["mnt_salario"].astype(float) + df["mnt_comision"].astype(float)).round(2)).any():
    errores.append("salario_total != mnt_salario + mnt_comision")
if df["empleado_id"].duplicated().any():
    errores.append("empleado_id duplicado en la salida")
total_join = df.loc[df["tiene_comision"], "mnt_comision"].astype(float).sum()
print(f"Filas={len(df)} | con comisión={int(df['tiene_comision'].sum())} | comisión total join={total_join:,.2f} | CSV={total_csv:,.2f}")
if total_join > total_csv + 0.01:
    errores.append("La comisión total del Join supera la del CSV")
if errores:
    sys.exit("ERROR: " + "; ".join(errores))
print("OK: Parquet validado")
