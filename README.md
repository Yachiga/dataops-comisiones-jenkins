# DataOps · Cálculo de salario total con comisiones

Flujo automatizado que combina la tabla **`dmc.rrhh.empleado`** (PostgreSQL) con el archivo
**`ComisionEmpleados_V1_AAAAMM.csv`** (Azure Blob Storage), hace un **Join por `empleado_id`**,
calcula

```
salario_total = mnt_salario + mnt_comision
```

y escribe el consolidado en **Parquet** en el Data Lake (ADLS Gen2). El despliegue a
**dev → test → prod** está automatizado con **Azure DevOps** (CI/CD) y plantillas **ARM**.

El flujo se entrega en dos implementaciones equivalentes:

| Implementación | Dónde | Uso |
|---|---|---|
| **Azure Data Factory** (principal) | `adf/` → `infra/arm/adf-content.json` | Producción, desplegada por CD |
| **Script Python** | `src/comisiones/` | Pruebas en CI, ejecución local o alternativa a ADF |

---

## Arquitectura

```
PostgreSQL dmc.rrhh.empleado ──Copy──► ADLS staging/rrhh/empleado/periodo=AAAAMM/empleado.parquet ─┐
                                                                                                   ├─► Data Flow (LEFT JOIN empleado_id)
Blob raw/comisiones/ComisionEmpleados_V1_AAAAMM.csv ──Validation──────────────────────────────────┘        │
                                                                                                            ▼
                                                     ADLS curated/comisiones/salario_total/periodo=AAAAMM/salario_total.parquet
```

* **Linked services:** `ls_postgres_dmc` (PostgreSQL V2, contraseña en Key Vault), `ls_blob_raw`
  (Blob, Managed Identity), `ls_adls_datalake` (ADLS Gen2, Managed Identity), `ls_keyvault`.
* **Pipeline `pl_comisiones_salario_total`:** `Validar_CSV_Comisiones` + `Copiar_Empleados_PostgreSQL`
  → `Join_Calcular_Salario_Total` (Data Flow) → `Fallo_Pipeline` si algo falla.
* **Trigger `tr_blob_nuevo_csv_comisiones`:** se dispara al llegar un nuevo CSV a `raw/comisiones/`.

### Reglas de negocio y calidad

* **LEFT JOIN** desde empleados: ningún empleado se pierde; quien no está en el CSV recibe
  comisión 0 y `tiene_comision = false`.
* Se rechaza el CSV si tiene `empleado_id` duplicados, valores no numéricos o comisiones negativas.
* `supera_tope_comision` marca las comisiones mayores que `mnt_tope_comision` (informativo; la
  fórmula pedida no aplica el tope).
* Las comisiones cuyo `empleado_id` no existe en la tabla se reportan en el log y en
  `reporte_ejecucion.json`.
* El CSV usa `;` como separador y el nombre viene como `"Nombre, Apellido"`: la coma es parte del texto.

### Columnas de salida

`empleado_id, tip_documento, num_documento, nombre_completo, nom_empleado, ape_empleado, cod_cargo,
cod_departamento, mnt_salario, mnt_comision, salario_total, mnt_tope_comision, tiene_comision,
supera_tope_comision, periodo, entorno, fecha_proceso`

---

## Estructura del repositorio

```
├── adf/                      # Artefactos ADF (formato Git de Data Factory) – fuente única de verdad
│   ├── linkedService/  dataset/  dataflow/  pipeline/  trigger/
├── infra/arm/
│   ├── infra.json            # Storage ADLS Gen2 + contenedores + Key Vault + Data Factory + RBAC
│   ├── adf-content.json      # Generado desde adf/ por scripts/build_adf_arm.py
│   └── parameters/infra.{dev,test,prod}.parameters.json
├── src/comisiones/           # Pipeline Python (config, extract, transform, load, pipeline)
├── tests/                    # pytest: transformación, flujo completo, artefactos ADF/ARM, secretos
├── scripts/
│   ├── build_adf_arm.py      # adf/ -> ARM parametrizado por entorno (--check en CI)
│   ├── smoke_test_adf.sh     # lanza el pipeline ADF y espera "Succeeded"
│   └── verify_parquet.py     # valida el Parquet escrito en curated
├── azure-pipelines.yml       # CI + CD dev/test/prod (Azure DevOps)
├── cicd/templates/deploy-env.yml
├── .github/workflows/ci-cd.yml  # alternativa GitHub Actions
├── data/input/ComisionEmpleados_V1_202610.csv
└── sql/extract_empleado.sql
```

---

## Ejecución local (Python)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # completar PG_PASSWORD
export $(grep -v '^#' .env | xargs)                    # o usar python-dotenv

# Pruebas
python -m pytest

# Contra la base PostgreSQL real + CSV local -> output/
PYTHONPATH=src python -m comisiones.pipeline --modo local --entorno dev \
  --csv data/input/ComisionEmpleados_V1_202610.csv

# Contra Azure (descarga el CSV del Blob y escribe Parquet en ADLS)
PYTHONPATH=src python -m comisiones.pipeline --modo azure --entorno dev
```

Salida local: `output/salario_total_202610.parquet`, `.xlsx`, `.csv` y `reporte_ejecucion.json`.
Códigos de salida: `0` éxito, `2` validación de calidad fallida, `1` error inesperado.

---

## Despliegue en Azure con Azure DevOps

### 1. Preparar Azure (una vez)

```bash
az login
az provider register --namespace Microsoft.DataFactory
az provider register --namespace Microsoft.EventGrid        # para el trigger de eventos
```

### 2. Preparar Azure DevOps (una vez)

1. **Repos:** crear el repositorio e importar este código (`git remote add origin … && git push -u origin --all`).
2. **Service connection** (*Project settings → Service connections → Azure Resource Manager →
   Workload Identity federation*), nombre **`sc-dataops-comisiones`**, con rol *Owner* o
   *Contributor + User Access Administrator* sobre la suscripción (las plantillas crean asignaciones RBAC).
3. **Variable group** **`vg-dataops-comisiones`** (*Pipelines → Library*):
   * `PG_PASSWORD` (secreta) – contraseña del usuario de solo lectura.
   * `AZURE_SUBSCRIPTION_ID`.
4. **Environments** (*Pipelines → Environments*): `dataops-dev`, `dataops-test`, `dataops-prod`.
   En `dataops-prod` → *Approvals and checks*: **Branch control** (solo `refs/heads/main`) y
   **Approvals** (aprobador) o una comprobación automática (*Business hours* / *Invoke REST API*).
5. **Pipelines → New pipeline → Azure Repos Git → Existing YAML** → `/azure-pipelines.yml`.
6. Opcional: **Branch policy** en `main` exigiendo que el pipeline pase en el Pull Request.

### 3. Flujo CI/CD

| Etapa | Cuándo | Qué hace |
|---|---|---|
| **CI** | todo push y PR a `main`/`develop` | ruff, pytest (JUnit + cobertura), ejecución de prueba del pipeline Python, `build_adf_arm.py --check`, `az deployment group validate`, publica artefacto `drop` |
| **CD_DEV** | push a `develop` o `main` | ARM infra → detiene trigger → ARM contenido ADF → sube CSV → ejecuta pipeline ADF (prueba de humo) → valida Parquet → activa trigger |
| **CD_TEST** | tras CD_DEV | igual que DEV en `rg-dataops-test` (trigger queda detenido) |
| **CD_PROD** | solo rama `main`, tras CD_TEST y los checks del environment | igual en `rg-dataops-prod` |

### 4. Flujo de trabajo Git

* `main` = producción, `develop` = integración, `feature/*` = cambios.
* Todo cambio entra por **Pull Request** a `develop`; la release se hace con PR `develop → main` y tag `vX.Y.Z`.
* Mensajes de commit con prefijos convencionales (`feat:`, `fix:`, `ci:`, `test:`, `docs:`).
* Si se edita el pipeline en el portal de ADF (modo Git), exportar los JSON a `adf/` y ejecutar
  `python scripts/build_adf_arm.py` antes de hacer commit; el CI falla si la plantilla no está sincronizada.

---

## Seguridad

* Ninguna contraseña se versiona: `PG_PASSWORD` vive en el variable group (secreto) y en Key Vault.
* ADF accede a Storage y Key Vault con **Managed Identity** (roles *Storage Blob Data Contributor*
  y *Key Vault Secrets User* asignados por la plantilla).
* Una prueba (`test_no_hay_secretos_en_el_repositorio`) falla si aparece un secreto en el código.

## Solución de problemas

| Síntoma | Causa probable |
|---|---|
| `Copiar_Empleados_PostgreSQL` falla por timeout | El servidor PostgreSQL no admite la IP del Azure IR: usar un Self-hosted IR o pedir apertura de firewall |
| Data Flow con columnas nulas | Tipos de la tabla distintos a la proyección: en ADF Studio → *Import projection* en `srcEmpleado` y volver a exportar |
| `AuthorizationFailed` al desplegar | La service connection no tiene permiso para crear *role assignments* |
| CI falla en `build_adf_arm.py --check` | Se cambió `adf/` sin regenerar `infra/arm/adf-content.json` |
