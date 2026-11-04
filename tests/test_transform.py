from pathlib import Path

import pandas as pd
import pytest

from comisiones import extract, transform
from comisiones.transform import ErrorCalidadDatos

RAIZ = Path(__file__).resolve().parents[1]
CSV_REAL = RAIZ / "data" / "input" / "ComisionEmpleados_V1_202610.csv"
FIXTURE_EMPLEADOS = RAIZ / "tests" / "fixtures" / "empleados_fixture.csv"


@pytest.fixture
def comisiones_reales():
    return extract.leer_csv_comisiones(CSV_REAL)


@pytest.fixture
def empleados():
    return extract.extraer_empleados_archivo(FIXTURE_EMPLEADOS)


# ---------------- Lectura del CSV ----------------
def test_csv_se_lee_con_separador_punto_y_coma(comisiones_reales):
    assert list(comisiones_reales.columns) == ["empleado_id", "Nombre y Apellido", "Comisión"]
    assert len(comisiones_reales) == 34


def test_csv_coma_en_nombre_no_rompe_columnas(comisiones_reales):
    fila = comisiones_reales[comisiones_reales["empleado_id"] == "29"].iloc[0]
    assert fila["Nombre y Apellido"] == "Ana Clara, Rojas"


def test_limpieza_tipos_y_total_comisiones(comisiones_reales):
    df = transform.limpiar_comisiones(comisiones_reales)
    assert df["empleado_id"].dtype == "int64"
    assert df["mnt_comision"].sum() == pytest.approx(354_000)
    assert df.loc[df.empleado_id == 18, "nombre_apellido_csv"].item() == "Juliana Martínez"


def test_periodo_desde_nombre_archivo():
    assert transform.periodo_desde_nombre("ComisionEmpleados_V1_202610.csv") == "202610"
    assert transform.periodo_desde_nombre("raw/ComisionEmpleados_V1_202510_2.csv") == "202510"
    assert transform.periodo_desde_nombre("otro.csv") is None


# ---------------- Join y cálculo ----------------
def test_salario_total_es_salario_mas_comision(empleados, comisiones_reales):
    df, _ = transform.calcular_salario_total(empleados, comisiones_reales, periodo="202610")
    assert (df["salario_total"] == df["mnt_salario"] + df["mnt_comision"]).all()


def test_left_join_conserva_todos_los_empleados(empleados, comisiones_reales):
    df, rep = transform.calcular_salario_total(empleados, comisiones_reales)
    assert len(df) == len(empleados) == rep.filas_salida
    assert rep.empleados_con_comision == 34
    assert rep.empleados_sin_comision == [6, 7, 8, 38]
    sin = df[df.empleado_id.isin([6, 7, 8, 38])]
    assert (sin["mnt_comision"] == 0).all()
    assert (sin["salario_total"] == sin["mnt_salario"]).all()


def test_valor_puntual_empleado_1(empleados, comisiones_reales):
    df, _ = transform.calcular_salario_total(empleados, comisiones_reales)
    fila = df[df.empleado_id == 1].iloc[0]
    assert fila["mnt_comision"] == 9000
    assert fila["salario_total"] == fila["mnt_salario"] + 9000


def test_marca_comision_sobre_tope(empleados, comisiones_reales):
    _, rep = transform.calcular_salario_total(empleados, comisiones_reales)
    assert rep.comisiones_sobre_tope == [18]  # 12 750 > tope 12 000


def test_totales_cuadran(empleados, comisiones_reales):
    df, rep = transform.calcular_salario_total(empleados, comisiones_reales)
    assert rep.total_salario_total == pytest.approx(rep.total_salario + rep.total_comision)
    assert rep.total_comision == pytest.approx(354_000)


def test_comision_sin_empleado_se_reporta(empleados):
    csv = "empleado_id;Nombre y Apellido;Comisión\n1;Juan, Pérez;100\n999;Fantasma, X;50\n"
    _, rep = transform.calcular_salario_total(empleados, extract.leer_csv_comisiones(csv))
    assert rep.comisiones_sin_empleado == [999]


# ---------------- Reglas de calidad ----------------
@pytest.mark.parametrize(
    "contenido, mensaje",
    [
        ("empleado_id;Nombre y Apellido;Comisión\n1;A, B;100\n1;A, B;200\n", "duplicados"),
        ("empleado_id;Nombre y Apellido;Comisión\n1;A, B;-5\n", "negativas"),
        ("empleado_id;Nombre y Apellido;Comisión\nX;A, B;10\n", "no numérica"),
        ("empleado_id;Nombre y Apellido\n1;A, B\n", "columnas"),
    ],
)
def test_reglas_de_calidad(contenido, mensaje):
    with pytest.raises(ErrorCalidadDatos, match=mensaje):
        transform.limpiar_comisiones(extract.leer_csv_comisiones(contenido))


def test_formato_decimal_con_coma():
    df = transform.limpiar_comisiones(extract.leer_csv_comisiones("empleado_id;Nombre y Apellido;Comisión\n1;A, B;9.000,50\n"))
    assert df["mnt_comision"].item() == pytest.approx(9000.50)


def test_empleados_duplicados_falla():
    emp = pd.DataFrame({"empleado_id": [1, 1], "mnt_salario": [1, 2]})
    with pytest.raises(ErrorCalidadDatos):
        transform.limpiar_empleados(emp)
