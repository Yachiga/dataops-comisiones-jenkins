"""Pruebas de integración del flujo completo en modo local (sin Azure)."""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from comisiones import pipeline
from comisiones.config import cargar_config

RAIZ = Path(__file__).resolve().parents[1]
TIENE_PYARROW = importlib.util.find_spec("pyarrow") is not None


def _args(tmp_path, *extra):
    return [
        "--modo", "local", "--entorno", "test",
        "--empleados-file", str(RAIZ / "tests/fixtures/empleados_fixture.csv"),
        "--csv", str(RAIZ / "data/input/ComisionEmpleados_V1_202610.csv"),
        "--salida", str(tmp_path), *extra,
    ]


def test_pipeline_local_genera_excel_y_reporte(tmp_path):
    assert pipeline.main(_args(tmp_path, "--formatos", "xlsx", "csv")) == 0
    rep = json.loads((tmp_path / "reporte_ejecucion.json").read_text(encoding="utf-8"))
    assert rep["estado"] == "Succeeded"
    assert rep["periodo"] == "202610"
    xlsx = pd.read_excel(tmp_path / "salario_total_202610.xlsx")
    assert len(xlsx) == 38
    assert {"empleado_id", "mnt_salario", "mnt_comision", "salario_total"} <= set(xlsx.columns)


@pytest.mark.skipif(not TIENE_PYARROW, reason="pyarrow no instalado")
def test_pipeline_local_genera_parquet(tmp_path):
    assert pipeline.main(_args(tmp_path, "--formatos", "parquet")) == 0
    df = pd.read_parquet(tmp_path / "salario_total_202610.parquet")
    assert len(df) == 38
    assert (df["salario_total"] == df["mnt_salario"] + df["mnt_comision"]).all()


def test_csv_invalido_devuelve_codigo_2(tmp_path):
    malo = tmp_path / "ComisionEmpleados_V1_209901.csv"
    malo.write_text("empleado_id;Nombre y Apellido;Comisión\n1;A, B;-1\n", encoding="utf-8")
    args = _args(tmp_path / "out", "--formatos", "csv")
    args[args.index("--csv") + 1] = str(malo)
    assert pipeline.main(args) == 2


def test_config_rechaza_entorno_invalido():
    with pytest.raises(ValueError):
        cargar_config("qa", requiere_postgres=False)


def test_config_exige_credenciales_postgres(monkeypatch):
    for var in ("PG_HOST", "PG_USER", "PG_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(OSError, match="PG_HOST"):
        cargar_config("dev", requiere_postgres=True)


def test_password_no_aparece_en_repr(monkeypatch):
    monkeypatch.setenv("PG_HOST", "h"); monkeypatch.setenv("PG_USER", "u"); monkeypatch.setenv("PG_PASSWORD", "secreto123")
    assert "secreto123" not in repr(cargar_config("dev").postgres)
