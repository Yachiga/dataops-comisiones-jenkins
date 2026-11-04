"""Genera la plantilla ARM del contenido de Data Factory a partir de la carpeta adf/.

La carpeta adf/ es la fuente única de verdad (mismo formato que usa la
integración Git de ADF). Este script la convierte en
``infra/arm/adf-content.json`` reemplazando los valores dependientes del
entorno por parámetros ARM, para que el mismo artefacto se despliegue en
dev, test y prod.

Uso:
    python scripts/build_adf_arm.py            # genera la plantilla
    python scripts/build_adf_arm.py --check    # falla si la plantilla versionada está desactualizada
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ADF = RAIZ / "adf"
SALIDA = RAIZ / "infra" / "arm" / "adf-content.json"

TIPOS = {
    "linkedService": ("Microsoft.DataFactory/factories/linkedservices", "LinkedServiceReference"),
    "dataset": ("Microsoft.DataFactory/factories/datasets", "DatasetReference"),
    "dataflow": ("Microsoft.DataFactory/factories/dataflows", "DataFlowReference"),
    "pipeline": ("Microsoft.DataFactory/factories/pipelines", "PipelineReference"),
    "trigger": ("Microsoft.DataFactory/factories/triggers", None),
}
REF_A_CARPETA = {v[1]: k for k, v in TIPOS.items() if v[1]}

PARAMETROS = {
    "factoryName": {"type": "string", "metadata": {"description": "Nombre del Data Factory destino"}},
    "entorno": {"type": "string", "allowedValues": ["dev", "test", "prod"]},
    "keyVaultUri": {"type": "string"},
    "blobEndpoint": {"type": "string"},
    "dfsEndpoint": {"type": "string"},
    "storageAccountId": {"type": "string"},
    "pgServer": {"type": "string", "defaultValue": "mgg.vps.webdock.cloud"},
    "pgDatabase": {"type": "string", "defaultValue": "dmc"},
    "pgUser": {"type": "string", "defaultValue": "usr_ro_dmc_rrhh_estudiantes"},
}

# (carpeta, nombre, ruta dentro de properties) -> expresión ARM
OVERRIDES = {
    ("linkedService", "ls_keyvault", ("typeProperties", "baseUrl")): "[parameters('keyVaultUri')]",
    ("linkedService", "ls_blob_raw", ("typeProperties", "serviceEndpoint")): "[parameters('blobEndpoint')]",
    ("linkedService", "ls_adls_datalake", ("typeProperties", "url")): "[parameters('dfsEndpoint')]",
    ("linkedService", "ls_postgres_dmc", ("typeProperties", "server")): "[parameters('pgServer')]",
    ("linkedService", "ls_postgres_dmc", ("typeProperties", "database")): "[parameters('pgDatabase')]",
    ("linkedService", "ls_postgres_dmc", ("typeProperties", "username")): "[parameters('pgUser')]",
    ("pipeline", "pl_comisiones_salario_total", ("parameters", "entorno", "defaultValue")): "[parameters('entorno')]",
    ("trigger", "tr_blob_nuevo_csv_comisiones", ("typeProperties", "scope")): "[parameters('storageAccountId')]",
}


def cargar_artefactos() -> dict[str, list[dict]]:
    return {carpeta: [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ADF / carpeta).glob("*.json"))] for carpeta in TIPOS}


def referencias(obj) -> set[tuple[str, str]]:
    """Devuelve {(carpeta, nombre)} referenciados dentro del objeto."""
    encontradas = set()
    if isinstance(obj, dict):
        if "referenceName" in obj and obj.get("type") in REF_A_CARPETA:
            encontradas.add((REF_A_CARPETA[obj["type"]], obj["referenceName"]))
        for v in obj.values():
            encontradas |= referencias(v)
    elif isinstance(obj, list):
        for v in obj:
            encontradas |= referencias(v)
    return encontradas


def escapar_arm(obj):
    """Los strings que empiezan con '[' son expresiones ARM; se escapan con '[['."""
    if isinstance(obj, dict):
        return {k: escapar_arm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [escapar_arm(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("["):
        return "[" + obj
    return obj


def asignar(d: dict, ruta: tuple[str, ...], valor):
    for k in ruta[:-1]:
        d = d[k]
    if ruta[-1] not in d:
        raise KeyError(f"Ruta {ruta} no existe")
    d[ruta[-1]] = valor


def validar(artefactos: dict[str, list[dict]]) -> list[str]:
    errores = []
    existentes = {(c, a["name"]) for c, lista in artefactos.items() for a in lista}
    for carpeta, lista in artefactos.items():
        for a in lista:
            for ref in referencias(a["properties"]):
                if ref not in existentes:
                    errores.append(f"{carpeta}/{a['name']} referencia a {ref[0]}/{ref[1]} que no existe")
    return errores


def construir() -> dict:
    artefactos = cargar_artefactos()
    errores = validar(artefactos)
    if errores:
        raise SystemExit("Errores de referencias:\n  " + "\n  ".join(errores))

    recursos = []
    for carpeta, (tipo_arm, _) in TIPOS.items():
        for a in artefactos[carpeta]:
            props = escapar_arm(copy.deepcopy(a["properties"]))
            for (c, n, ruta), expr in OVERRIDES.items():
                if c == carpeta and n == a["name"]:
                    asignar(props, ruta, expr)
            if carpeta == "trigger":
                for p in props.get("pipelines", []):
                    if "entorno" in p.get("parameters", {}):
                        p["parameters"]["entorno"] = "[parameters('entorno')]"
            depende = sorted(
                f"[resourceId('{TIPOS[c][0]}', parameters('factoryName'), '{n}')]"
                for c, n in referencias(a["properties"])
            )
            recursos.append({
                "name": f"[concat(parameters('factoryName'), '/{a['name']}')]",
                "type": tipo_arm,
                "apiVersion": "2018-06-01",
                "properties": props,
                "dependsOn": depende,
            })
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "contentVersion": "1.0.0.0",
        "metadata": {"description": "Contenido de Data Factory (generado por scripts/build_adf_arm.py; no editar a mano)"},
        "parameters": PARAMETROS,
        "resources": recursos,
        "outputs": {"recursos": {"type": "int", "value": len(recursos)}},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    plantilla = json.dumps(construir(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        actual = SALIDA.read_text(encoding="utf-8") if SALIDA.exists() else ""
        if actual != plantilla:
            print("ERROR: infra/arm/adf-content.json está desactualizada. Ejecute scripts/build_adf_arm.py")
            return 1
        print("OK: plantilla ARM de ADF al día")
        return 0
    SALIDA.write_text(plantilla, encoding="utf-8")
    n = len(json.loads(plantilla)["resources"])
    print(f"Plantilla generada: {SALIDA.relative_to(RAIZ)} ({n} recursos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
