"""Validaciones estáticas de los artefactos de Data Factory, ARM y seguridad del repositorio."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
import build_adf_arm  # noqa: E402

JSONS = sorted(list((RAIZ / "adf").rglob("*.json")) + list((RAIZ / "infra").rglob("*.json")))


@pytest.mark.parametrize("ruta", JSONS, ids=lambda p: str(p.relative_to(RAIZ)))
def test_json_valido(ruta):
    json.loads(ruta.read_text(encoding="utf-8"))


def test_nombre_de_archivo_coincide_con_artefacto():
    for ruta in (RAIZ / "adf").rglob("*.json"):
        assert json.loads(ruta.read_text(encoding="utf-8"))["name"] == ruta.stem


def test_referencias_adf_resueltas():
    assert build_adf_arm.validar(build_adf_arm.cargar_artefactos()) == []


def test_plantilla_arm_versionada_esta_al_dia():
    r = subprocess.run([sys.executable, str(RAIZ / "scripts/build_adf_arm.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_plantilla_arm_parametriza_entorno():
    plantilla = build_adf_arm.construir()
    texto = json.dumps(plantilla)
    for valor_dev in ("stdataopsdev", "kv-dataops-dev", "rg-dataops-dev"):
        assert valor_dev not in texto, f"Valor de dev '{valor_dev}' quedó fijo en la plantilla"
    assert len(plantilla["resources"]) == 11


def test_dataflow_hace_join_por_empleado_id_y_calcula_salario_total():
    df = json.loads((RAIZ / "adf/dataflow/df_join_salario_total.json").read_text(encoding="utf-8"))
    script = "\n".join(df["properties"]["typeProperties"]["scriptLines"])
    assert re.search(r"join\(empleado_id == com_empleado_id,\s*joinType:'left'", script)
    assert "salario_total = toDecimal(mnt_salario + mnt_comision" in script
    assert "format: 'parquet'" in script.split("sinkSalarioTotal")[0].split("ordEmpleado sink")[1]


def test_pipeline_orden_de_actividades():
    pl = json.loads((RAIZ / "adf/pipeline/pl_comisiones_salario_total.json").read_text(encoding="utf-8"))
    acts = {a["name"]: a for a in pl["properties"]["activities"]}
    assert acts["Copiar_Empleados_PostgreSQL"]["typeProperties"]["source"]["query"].endswith("FROM rrhh.empleado")
    deps = {d["activity"] for d in acts["Join_Calcular_Salario_Total"]["dependsOn"]}
    assert deps == {"Validar_CSV_Comisiones", "Copiar_Empleados_PostgreSQL"}


def test_no_hay_secretos_en_el_repositorio():
    patron = re.compile(r"fZp" r"!jHt0|AccountKey=[A-Za-z0-9+/]{20,}|\"password\"\s*:\s*\"[^\"]+\"", re.IGNORECASE)
    excluidos = {".git", ".venv", "output", "__pycache__", ".pytest_cache"}
    for ruta in RAIZ.rglob("*"):
        if ruta.is_file() and ruta != Path(__file__).resolve() and not (set(ruta.relative_to(RAIZ).parts) & excluidos) and ruta.suffix in {".py", ".json", ".yml", ".yaml", ".md", ".sql", ".sh", ".txt"}:
            assert not patron.search(ruta.read_text(encoding="utf-8", errors="ignore")), f"Posible secreto en {ruta}"


def test_parametros_por_entorno_existen():
    for env in ("dev", "test", "prod"):
        p = json.loads((RAIZ / f"infra/arm/parameters/infra.{env}.parameters.json").read_text())
        assert p["parameters"]["entorno"]["value"] == env
        assert "pgPassword" not in p["parameters"], "La contraseña se inyecta desde el pipeline, no desde el archivo"


@pytest.mark.parametrize("ruta", ["azure-pipelines.yml", "cicd/templates/deploy-env.yml", ".github/workflows/ci-cd.yml"])
def test_yaml_cicd_valido(ruta):
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((RAIZ / ruta).read_text(encoding="utf-8"))
    assert "stages" in doc or "jobs" in doc


def test_cd_cubre_los_tres_entornos():
    texto = (RAIZ / "azure-pipelines.yml").read_text(encoding="utf-8")
    for env in ("dev", "test", "prod"):
        assert f"entorno: {env}" in texto
    assert "refs/heads/main" in texto  # prod solo desde main


def test_infra_no_requiere_permisos_de_owner():
    """Cuentas de laboratorio suelen tener solo Contributor: la plantilla no debe crear roleAssignments."""
    infra = json.loads((RAIZ / "infra/arm/infra.json").read_text(encoding="utf-8"))
    tipos = [r["type"] for r in infra["resources"]]
    assert "Microsoft.Authorization/roleAssignments" not in tipos
    assert "Microsoft.KeyVault/vaults/accessPolicies" in tipos
    secretos = {r["name"].split("/")[-1].rstrip("')]") for r in infra["resources"] if r["type"].endswith("/secrets")}
    assert {"pg-dmc-password", "storage-account-key", "storage-connection-string"} <= secretos


def test_linked_services_leen_secretos_de_key_vault():
    for nombre in ("ls_postgres_dmc", "ls_blob_raw", "ls_adls_datalake"):
        texto = (RAIZ / f"adf/linkedService/{nombre}.json").read_text(encoding="utf-8")
        assert '"AzureKeyVaultSecret"' in texto, nombre


@pytest.mark.parametrize("script", ["scripts/deploy.sh", "scripts/smoke_test_adf.sh", "scripts/publicar_github.sh"])
def test_scripts_bash_sintaxis(script):
    r = subprocess.run(["bash", "-n", str(RAIZ / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_jenkinsfile_cubre_ci_y_tres_entornos_con_aprobacion():
    j = (RAIZ / "Jenkinsfile").read_text(encoding="utf-8")
    for etapa in ("CI - Pruebas", "CD - dev", "CD - test", "CD - prod", "Aprobación producción"):
        assert f"stage('{etapa}')" in j
    assert "input message" in j and "junit" in j
    assert j.count("{") == j.count("}")


def test_ci_cd_reutilizan_deploy_sh():
    for ruta in ("cicd/templates/deploy-env.yml", "Jenkinsfile", ".github/workflows/ci-cd.yml"):
        assert "deploy.sh" in (RAIZ / ruta).read_text(encoding="utf-8"), ruta
