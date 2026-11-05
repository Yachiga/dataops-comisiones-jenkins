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
  (Blob) y `ls_adls_datalake` (ADLS Gen2) con la clave del Storage guardada en Key Vault, `ls_keyvault`.
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
│   ├── infra.json            # Storage ADLS Gen2 + contenedores + Key Vault (secretos) + Data Factory
│   ├── adf-content.json      # Generado desde adf/ por scripts/build_adf_arm.py
│   └── parameters/infra.{dev,test,prod}.parameters.json
├── src/comisiones/           # Pipeline Python (config, extract, transform, load, pipeline)
├── tests/                    # pytest: transformación, flujo completo, artefactos ADF/ARM, secretos
├── scripts/
│   ├── build_adf_arm.py      # adf/ -> ARM parametrizado por entorno (--check en CI)
│   ├── deploy.sh             # despliegue completo de un entorno (lo usan todos los CI/CD)
│   ├── publicar_github.sh    # sube ramas y etiquetas a GitHub
│   ├── smoke_test_adf.sh     # lanza el pipeline ADF y espera "Succeeded"
│   └── verify_parquet.py     # valida el Parquet escrito en curated
├── azure-pipelines.yml       # CI + CD dev/test/prod (Azure DevOps)
├── cicd/templates/deploy-env.yml
├── Jenkinsfile               # CI + CD dev/test/prod (Jenkins)
├── .github/workflows/ci-cd.yml  # alternativa GitHub Actions (opcional)
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

## Publicar el repositorio en GitHub

1. Crear el repositorio **vacío** `dataops-comisiones` en https://github.com/new con la cuenta `yachiga`
   (sin README ni .gitignore).
2. Crear un *Personal Access Token* (Settings → Developer settings → Tokens, permiso `repo`): GitHub
   lo pide como contraseña al hacer `git push`.
3. Desde la carpeta del proyecto:

```bash
bash scripts/publicar_github.sh yachiga dataops-comisiones   # sube main, develop y las etiquetas
```

---

## Despliegue en Azure

Toda la lógica de despliegue está en **`scripts/deploy.sh <dev|test|prod>`**: ARM de
infraestructura → detener trigger → ARM del contenido ADF → subir CSV → ejecutar el pipeline ADF
(prueba de humo) → validar el Parquet → activar trigger. Lo llaman Azure DevOps, Jenkins y GitHub
Actions, y también se puede ejecutar a mano.

La plantilla **no crea asignaciones de roles**: basta el rol *Contributor* (cuentas de laboratorio).
ADF lee la contraseña de PostgreSQL y la clave del Storage desde Key Vault mediante una *access
policy* de su Managed Identity.

### 1. Preparar Azure (una vez)

```bash
az login                                                     # abre el navegador (admite MFA)
az account show -o table                                     # confirmar la suscripción del curso
az provider register --namespace Microsoft.DataFactory
az provider register --namespace Microsoft.EventGrid        # para el trigger de eventos
```

### 2. Despliegue manual (sin herramienta de CI/CD)

```bash
export PG_PASSWORD='<contraseña de usr_ro_dmc_rrhh_estudiantes>'
export RESOURCE_GROUP='<grupo asignado por el curso>'        # opcional; por defecto rg-dataops-<entorno>
bash scripts/deploy.sh dev
```

### 3. Opción A – Azure DevOps

1. Crear un proyecto en https://dev.azure.com.
2. **Service connection** (*Project settings → Service connections → Azure Resource Manager →
   Workload Identity federation (automatic)*), nombre **`sc-dataops-comisiones`**, con alcance al
   grupo de recursos o a la suscripción. Si la cuenta del curso no puede crear app registrations,
   pedir al docente un Service Principal y usar *Service principal (manual)*.
3. **Variable group** **`vg-dataops-comisiones`** (*Pipelines → Library*): `PG_PASSWORD` (secreta) y
   `AZURE_SUBSCRIPTION_ID`. Si solo hay un grupo de recursos, editar `resourceGroup_dev/test/prod`
   en `azure-pipelines.yml` con ese nombre.
4. **Environments** (*Pipelines → Environments*): `dataops-dev`, `dataops-test`, `dataops-prod`.
   En `dataops-prod` → *Approvals and checks*: **Branch control** (solo `refs/heads/main`) y
   **Approvals** o una comprobación automática (*Business hours* / *Invoke REST API*).
5. **Pipelines → New pipeline → GitHub → yachiga/dataops-comisiones → Existing YAML** →
   `/azure-pipelines.yml`.

| Etapa | Cuándo | Qué hace |
|---|---|---|
| **CI** | todo push y PR a `main`/`develop` | ruff, pytest (JUnit + cobertura), ejecución de prueba del pipeline Python, `build_adf_arm.py --check`, `az deployment group validate`, publica artefacto `drop` |
| **CD_DEV** | push a `develop` o `main` | `scripts/deploy.sh dev` |
| **CD_TEST** | tras CD_DEV | `scripts/deploy.sh test` (trigger queda detenido) |
| **CD_PROD** | solo rama `main`, tras CD_TEST y los checks del environment | `scripts/deploy.sh prod` |

### 4. Opción C – GitHub Actions (activa en el repositorio)

`.github/workflows/ci-cd.yml` ejecuta CI en cada push y PR, y CD dev → test → prod (prod solo
desde `main`, con aprobación del environment `prod`). El despliegue está en
`.github/workflows/deploy.yml`:

* Variable de repositorio `DESTINO=local` (por defecto): ejecuta el pipeline Python contra la base
  PostgreSQL real y publica el Parquet como artefacto `datalake-<entorno>`.
* `DESTINO=azure`: ejecuta `scripts/deploy.sh` (requiere los secrets `AZURE_CLIENT_ID`,
  `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`).
* Secret obligatorio: `PG_PASSWORD` (*Settings → Secrets and variables → Actions*).

### 5. Opción B – Jenkins

1. Jenkins con los plugins *Pipeline*, *Git*, *GitHub Branch Source*, *Credentials Binding* y *JUnit*;
   el agente necesita `python3`, `git` y Azure CLI.
2. Credenciales (*Manage Jenkins → Credentials*): `pg-password` (Secret text) y, para desplegar en
   Azure, `azure-sp` (Username with password: appId / secret) y `azure-tenant-id` (Secret text).
3. *New Item → Multibranch Pipeline* → fuente GitHub `https://github.com/yachiga/dataops-comisiones.git`
   → *Script Path* `Jenkinsfile`.
4. Parámetro **DESTINO**: `azure` (despliega con `deploy.sh`) o `local` (ejecuta el pipeline Python
   contra PostgreSQL y deja el Parquet en `datalake/<entorno>/`, sin Azure).

Etapas: Preparar entorno → CI Lint → CI Pruebas (JUnit) → CI Validar ADF/ARM → CI Ejecución de
prueba → CD dev → CD test → **Aprobación producción** (`input`, solo `main`) → CD prod.

### 4. Flujo de trabajo Git

* `main` = producción, `develop` = integración, `feature/*` = cambios.
* Todo cambio entra por **Pull Request** a `develop`; la release se hace con PR `develop → main` y tag `vX.Y.Z`.
* Mensajes de commit con prefijos convencionales (`feat:`, `fix:`, `ci:`, `test:`, `docs:`).
* Si se edita el pipeline en el portal de ADF (modo Git), exportar los JSON a `adf/` y ejecutar
  `python scripts/build_adf_arm.py` antes de hacer commit; el CI falla si la plantilla no está sincronizada.

---

## Seguridad

* Ninguna contraseña se versiona: `PG_PASSWORD` vive en el variable group (secreto) y en Key Vault.
* ADF lee de Key Vault la contraseña de PostgreSQL y la clave del Storage (access policy de su
  Managed Identity). Con permisos de Owner se puede pasar a roles RBAC y prescindir de la clave.
* Una prueba (`test_no_hay_secretos_en_el_repositorio`) falla si aparece un secreto en el código.

## Solución de problemas

| Síntoma | Causa probable |
|---|---|
| `Copiar_Empleados_PostgreSQL` falla por timeout | El servidor PostgreSQL no admite la IP del Azure IR: usar un Self-hosted IR o pedir apertura de firewall |
| Data Flow con columnas nulas | Tipos de la tabla distintos a la proyección: en ADF Studio → *Import projection* en `srcEmpleado` y volver a exportar |
| `AuthorizationFailed` al desplegar | La cuenta o service connection no tiene *Contributor* sobre el grupo de recursos |
| `az group create` rechazado | La cuenta del curso no puede crear grupos: usar `RESOURCE_GROUP` con el grupo asignado |
| CI falla en `build_adf_arm.py --check` | Se cambió `adf/` sin regenerar `infra/arm/adf-content.json` |
