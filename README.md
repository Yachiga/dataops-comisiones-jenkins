# Proyecto DataOps · Cálculo del salario total con comisiones

**Curso:** DE – DataOps (DMC) · Asignación Proyecto 60%  
**Tema:** Proyecto DataOps con Azure DevOps y Azure Data Factory  
**Alumno:** Yvan Chirinos · **Docente:** Miguel Ángel García

> En este repositorio el CI/CD corre en **GitHub Actions** (`.github/workflows/`). También dejé listas las
> definiciones para Azure DevOps (`azure-pipelines.yml`) y Jenkins (`Jenkinsfile`).
> Versión ejecutada con Jenkins: https://github.com/Yachiga/dataops-comisiones-jenkins

## Sobre este proyecto

Este repositorio es mi solución a la asignación del curso. El caso es un cliente que quiere calcular
cada mes el salario total de sus empleados juntando la tabla `dmc.rrhh.empleado` (PostgreSQL) con un
CSV de comisiones, y que ese flujo se despliegue solo, de desarrollo a producción, con CI/CD.

Lo que construí:

* Un **pipeline en Python** que extrae los empleados de PostgreSQL, lee el CSV, hace el Join por
  `empleado_id`, calcula `salario_total` y genera un **Parquet**. Es el que se ejecuta en los tres entornos.
* El **mismo flujo en Azure Data Factory** (copy, validación, data flow y trigger), con **plantillas ARM**
  para desplegar el Storage, el Key Vault y el Data Factory por entorno.
* Un **CI/CD en GitHub Actions** que, en cada cambio, corre el lint, las 58 pruebas y la validación de las
  plantillas, y luego despliega a **dev → test → prod**. Producción solo se despliega desde `main` y con mi aprobación.

Empecé el trabajo con la idea de usar Azure DevOps, pero a mitad del proyecto la cuenta de Azure del
curso dejó de mostrar la suscripción, y Azure DevOps necesita esa conexión para desplegar. Por eso
ejecuté el CI/CD en GitHub Actions con las mismas etapas y aprobaciones, y dejé `azure-pipelines.yml`
listo para cuando vuelva el acceso. El pipeline de Data Factory y las plantillas ARM quedaron validados
pero no desplegados; en la [sección 7](#7-paso-a-paso-despliegue-en-azure-arm--data-factory) explico cómo desplegarlos.

## Índice

0. [Sobre este proyecto](#sobre-este-proyecto)
1. [Objetivo](#1-objetivo)
2. [Contenido del repositorio](#2-contenido-del-repositorio)
3. [Arquitectura y flujo de datos](#3-arquitectura-y-flujo-de-datos)
4. [Requisitos previos](#4-requisitos-previos)
5. [Paso a paso: ejecución local](#5-paso-a-paso-ejecución-local)
6. [Paso a paso: CI/CD con GitHub Actions (dev → test → prod)](#6-paso-a-paso-cicd-con-github-actions-dev--test--prod)
7. [Paso a paso: despliegue en Azure (ARM + Data Factory)](#7-paso-a-paso-despliegue-en-azure-arm--data-factory)
8. [Paso a paso: CI/CD con Azure DevOps y Jenkins](#8-paso-a-paso-cicd-con-azure-devops-y-jenkins)
9. [Flujo de trabajo Git](#9-flujo-de-trabajo-git)
10. [Resultados esperados y verificación](#10-resultados-esperados-y-verificación)
11. [Seguridad](#11-seguridad)
12. [Solución de problemas](#12-solución-de-problemas)
13. [Lo que aprendí](#13-lo-que-aprendí)

---

## 1. Objetivo

El objetivo es automatizar el cálculo del **salario total** de cada empleado:

1. **Extraer** la tabla `dmc.rrhh.empleado` de PostgreSQL (`mgg.vps.webdock.cloud:5432`, base `dmc`, esquema `rrhh`).
2. **Procesar** el archivo de comisiones `ComisionEmpleados_V1_AAAAMM.csv`.
3. **Unir** ambas fuentes por `empleado_id`.
4. **Calcular**

   ```
   salario_total = mnt_salario + mnt_comision
   ```

5. **Escribir** la tabla consolidada en formato **Parquet** en el Data Lake (también Excel y CSV en modo local).
6. **Desplegar** automáticamente a los entornos **dev → test → prod**, con pruebas y aprobación antes de producción.

Implementé el flujo de dos formas equivalentes:

| Implementación | Carpeta | Cuándo se usa |
|---|---|---|
| **Script Python** | `src/comisiones/` | Lo ejecuta GitHub Actions en cada entorno (`DESTINO=local`), en local y en las pruebas |
| **Azure Data Factory** | `adf/` → `infra/arm/adf-content.json` | Despliegue en Azure (`DESTINO=azure`) con plantillas ARM |

---

## 2. Contenido del repositorio

```
dataops-comisiones/
├── .github/workflows/
│   ├── ci-cd.yml                   # CI/CD ACTIVO: CI → CD dev → CD test → CD prod (con aprobación)
│   └── deploy.yml                  # despliegue reutilizable de un entorno
├── azure-pipelines.yml             # CI/CD equivalente para Azure DevOps
├── cicd/templates/deploy-env.yml   # plantilla de despliegue por entorno (Azure DevOps)
├── Jenkinsfile                     # CI/CD equivalente para Jenkins
├── README.md                       # este documento
├── requirements.txt                # dependencias del pipeline (pandas, pyarrow, SQLAlchemy, psycopg2, azure-*)
├── requirements-dev.txt            # + pytest, pytest-cov, ruff, PyYAML (CI)
├── pyproject.toml                  # configuración de pytest y ruff
├── .env.example                    # plantilla de variables (PG_HOST, PG_USER, PG_PASSWORD vacío…)
│
├── src/comisiones/                 # PIPELINE PYTHON
│   ├── config.py                   #   lee variables de entorno por entorno (dev/test/prod); oculta la contraseña
│   ├── extract.py                  #   PostgreSQL (SQLAlchemy) y lectura del CSV (separador ";")
│   ├── transform.py                #   limpieza, reglas de calidad, LEFT JOIN y salario_total
│   ├── load.py                     #   escritura Parquet/Excel/CSV local o en ADLS Gen2
│   └── pipeline.py                 #   orquestador (CLI: --entorno --modo --csv --salida --formatos)
│
├── adf/                            # PIPELINE DE AZURE DATA FACTORY (formato Git de ADF)
│   ├── linkedService/              #   ls_postgres_dmc, ls_blob_raw, ls_adls_datalake, ls_keyvault
│   ├── dataset/                    #   ds_pg_empleado, ds_csv_comisiones, ds_parquet_staging_empleado,
│   │                               #   ds_parquet_curated_salario_total
│   ├── dataflow/                   #   df_join_salario_total (LEFT JOIN + salario_total)
│   ├── pipeline/                   #   pl_comisiones_salario_total
│   └── trigger/                    #   tr_blob_nuevo_csv_comisiones (al llegar un CSV nuevo)
│
├── infra/arm/                      # PLANTILLAS ARM
│   ├── infra.json                  #   Storage ADLS Gen2 + contenedores + Key Vault + secretos + Data Factory
│   ├── adf-content.json            #   contenido de ADF (generado desde adf/ por scripts/build_adf_arm.py)
│   └── parameters/
│       ├── infra.dev.parameters.json
│       ├── infra.test.parameters.json
│       └── infra.prod.parameters.json
│
├── scripts/
│   ├── build_adf_arm.py            # convierte adf/ en la plantilla ARM; --check falla si no está sincronizada
│   ├── deploy.sh                   # despliegue completo de un entorno en Azure (7 pasos)
│   ├── smoke_test_adf.sh           # ejecuta el pipeline de ADF y espera "Succeeded"
│   ├── verify_parquet.py           # valida el Parquet (local o en ADLS): fórmula, duplicados y totales
│   └── publicar_github.sh          # sube ramas y etiquetas a GitHub
│
├── tests/                          # 58 PRUEBAS (pytest)
│   ├── test_transform.py           #   lectura del CSV, Join, fórmula, reglas de calidad
│   ├── test_pipeline.py            #   flujo completo, códigos de salida, configuración, contraseña oculta
│   ├── test_adf_artifacts.py       #   JSON de ADF/ARM, referencias, plantilla al día, CI/CD, sin secretos
│   └── fixtures/empleados_fixture.csv
│
├── data/input/ComisionEmpleados_V1_202610.csv   # archivo de comisiones del periodo 202610
├── sql/extract_empleado.sql                     # consulta de extracción
└── docs/                                        # diagramas de arquitectura y evidencias (logs y capturas)
```

---

## 3. Arquitectura y flujo de datos

### 3.1 Flujo con Python (lo que ejecuta el CI/CD)

```
PostgreSQL dmc.rrhh.empleado ──extract.py──┐
                                            ├──► transform.py (LEFT JOIN por empleado_id, salario_total)
data/input/ComisionEmpleados_V1_202610.csv ┘                │
                                                             ▼
                                   load.py ──► datalake/<entorno>/salario_total_202610.parquet (+ .xlsx, .csv)
                                                             │
                                                             ▼
                                         verify_parquet.py ──► "OK: Parquet validado"
```

### 3.2 Flujo con Azure Data Factory

```
PostgreSQL dmc.rrhh.empleado ──Copy──► ADLS staging/rrhh/empleado/periodo=AAAAMM/empleado.parquet ─┐
                                                                                                   ├─► Data Flow df_join_salario_total
Blob raw/comisiones/ComisionEmpleados_V1_AAAAMM.csv ──Validation──────────────────────────────────┘        │
                                                                                                            ▼
                                                     ADLS curated/comisiones/salario_total/periodo=AAAAMM/salario_total.parquet
```

* **Pipeline `pl_comisiones_salario_total`:** `Validar_CSV_Comisiones` y `Copiar_Empleados_PostgreSQL` en paralelo → `Join_Calcular_Salario_Total` (Data Flow) → `Fallo_Pipeline` si algo falla.
* **Linked services:** las contraseñas (PostgreSQL y Storage) se leen de **Key Vault**.
* **Trigger:** `tr_blob_nuevo_csv_comisiones` ejecuta el pipeline cuando llega un CSV nuevo a `raw/comisiones/`.

### 3.3 Reglas de negocio y calidad

| Regla | Comportamiento |
|---|---|
| LEFT JOIN desde empleados | Ningún empleado se pierde; quien no está en el CSV recibe comisión 0 y `tiene_comision = false` |
| `empleado_id` duplicado en el CSV | El pipeline se detiene (código de salida 2) |
| Comisión negativa o no numérica | El pipeline se detiene (código de salida 2) |
| Comisión sin empleado en la tabla | Se reporta en el log y en `reporte_ejecucion.json` |
| Comisión mayor que `mnt_tope_comision` | Se marca en `supera_tope_comision` (informativo, no se recorta) |
| Formato del CSV | Separador `;`; el nombre viene como `"Nombre, Apellido"` y la coma es parte del texto |

**Columnas de salida:** `empleado_id, tip_documento, num_documento, nombre_completo, nom_empleado, ape_empleado, cod_cargo, cod_departamento, mnt_salario, mnt_comision, salario_total, mnt_tope_comision, tiene_comision, supera_tope_comision, periodo, entorno, fecha_proceso`.

---

## 4. Requisitos previos

| Requisito | Versión | Para qué |
|---|---|---|
| Git | cualquiera | clonar el repositorio |
| Python | 3.10 o superior | ejecución local (GitHub Actions usa 3.11) |
| Acceso a PostgreSQL | usuario de solo lectura `usr_ro_dmc_rrhh_estudiantes` | extraer `rrhh.empleado` |
| Cuenta de GitHub | con GitHub Actions habilitado | alojar el repositorio y ejecutar el CI/CD |
| Suscripción de Azure + Azure CLI | solo para `DESTINO=azure` | desplegar ARM y Data Factory |

---

## 5. Paso a paso: ejecución local

Así lo ejecuto en mi equipo antes de subir cambios:

**Paso 1 – Clonar el repositorio**

```bash
git clone https://github.com/Yachiga/dataops-comisiones.git
cd dataops-comisiones
```

**Paso 2 – Crear el entorno virtual e instalar dependencias**

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

```bash
# Linux / macOS
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

**Paso 3 – Configurar las variables**

Copiar `.env.example` a `.env` y completar `PG_PASSWORD` (el archivo `.env` no se versiona). O definirlas en la sesión:

```powershell
$env:PG_HOST="mgg.vps.webdock.cloud"; $env:PG_USER="usr_ro_dmc_rrhh_estudiantes"; $env:PG_DATABASE="dmc"
$env:PG_PASSWORD="<contraseña>"; $env:PYTHONPATH="src"
```

**Paso 4 – Ejecutar las pruebas**

```bash
python -m pytest            # 58 pruebas; no necesitan la base de datos
ruff check src tests scripts
```

**Paso 5 – Ejecutar el pipeline contra la base real**

```bash
python -m comisiones.pipeline --modo local --entorno dev \
  --csv data/input/ComisionEmpleados_V1_202610.csv --salida datalake/dev --formatos parquet xlsx csv
```

**Paso 6 – Validar la salida**

```bash
python scripts/verify_parquet.py --ruta datalake/dev --csv data/input/ComisionEmpleados_V1_202610.csv
```

Se generan `salario_total_202610.parquet`, `.xlsx`, `.csv` y `reporte_ejecucion.json`.
Códigos de salida del pipeline: `0` éxito, `2` validación de calidad fallida, `1` error inesperado.

---

## 6. Paso a paso: CI/CD con GitHub Actions (dev → test → prod)

### 6.1 Cómo funciona

```
feature/*  ──merge──►  develop  ──PR──►  main
                          │                │
                          ▼                ▼
                   CI → CD dev →     CI → CD dev → CD test → Aprobación → CD prod
                        CD test
```

| # | Job | Cuándo corre | Qué hace | Si falla |
|---|---|---|---|---|
| 1 | CI - validar y probar | todo push y Pull Request a `main`/`develop` | ruff, 58 pruebas con JUnit y cobertura, `build_adf_arm.py --check`, ejecución de prueba con fixture; publica `ci-reportes` | no se despliega nada |
| 2 | CD - dev | push a `develop` o `main` (no en PR) | pipeline contra PostgreSQL real → Parquet en `datalake/dev/` + `verify_parquet.py`; publica el artefacto `datalake-dev` | no despliega test ni prod |
| 3 | CD - test | después de dev | lo mismo en `datalake/test/` (artefacto `datalake-test`) | no despliega prod |
| 4 | CD - prod | solo `main`, después de test | espera la aprobación del environment `prod` y despliega a `datalake/prod/` (artefacto `datalake-prod`) | — |

El despliegue de cada entorno está en `.github/workflows/deploy.yml` y lo reutilizan los tres jobs de CD.

### 6.2 Paso 1 – Publicar el repositorio

```bash
git remote add origin https://github.com/<usuario>/dataops-comisiones.git
git push -u origin main develop --tags
```

GitHub pide un *Personal Access Token* (Settings → Developer settings → Tokens) como contraseña. También
se puede usar `bash scripts/publicar_github.sh <usuario> dataops-comisiones`.

### 6.3 Paso 2 – Crear el secret de la base de datos

1. **Settings → Secrets and variables → Actions → New repository secret**.
2. **Name:** `PG_PASSWORD` · **Secret:** contraseña del usuario `usr_ro_dmc_rrhh_estudiantes`.
3. **Add secret**. Sin este secret, los jobs de CD fallan con "Falta el secret PG_PASSWORD".

### 6.4 Paso 3 – Configurar los environments y la aprobación de producción

1. **Settings → Environments → New environment**: crear `dev`, `test` y `prod`.
2. En `prod`:
   * **Required reviewers:** agregar mi usuario (`Yachiga`).
   * **Deployment branches and tags:** *Selected branches* → `main`.
3. **Save protection rules**.

### 6.5 Paso 4 – (Opcional) Elegir el destino

En **Settings → Secrets and variables → Actions → Variables**:

| Variable | Valor | Efecto |
|---|---|---|
| `DESTINO` | `local` (por defecto si no existe) | pipeline Python contra PostgreSQL; el Parquet queda como artefacto |
| `DESTINO` | `azure` | `scripts/deploy.sh`: ARM + Data Factory (ver 7.4) |

### 6.6 Paso 5 – Ejecutar el CI/CD

* **Automático:** cada push a `develop` o `main`, y cada Pull Request (solo CI).
* **Manual:** **Actions → ci-cd-comisiones → Run workflow** → elegir la rama.

### 6.7 Paso 6 – Aprobar el paso a producción

Cuando la ejecución de `main` llega a **CD - prod**, queda en *Waiting*:

1. Abrir la ejecución en **Actions** → **Review deployments**.
2. Marcar `prod`, escribir un comentario (por ejemplo "Aprobado para producción") y pulsar **Approve and deploy**.
3. GitHub registra quién aprobó y cuándo.

### 6.8 Paso 7 – Verificar el despliegue en cada entorno

| Qué revisar | Dónde | Resultado esperado |
|---|---|---|
| Estado de la ejecución | **Actions** → ejecución | CI, dev, test y prod en verde |
| Pruebas | resumen del job CI | 58 aprobadas, 0 fallidas, 0 omitidas |
| Log de cada entorno | job **CD - dev / test / prod** → paso "Pipeline Python contra PostgreSQL" | `Empleados extraídos de PostgreSQL: 48 filas`, `"estado": "Succeeded"` |
| Validación del Parquet | resumen del job de cada entorno | tabla de indicadores y "OK: Parquet validado" |
| Archivos generados | **Artifacts** de la ejecución | `datalake-dev`, `datalake-test`, `datalake-prod` con el Parquet, Excel, CSV y `reporte_ejecucion.json` |
| Despliegues | página principal → **Deployments** | `dev`, `test` y `prod` activos |

---

## 7. Paso a paso: despliegue en Azure (ARM + Data Factory)

Toda la lógica está en `scripts/deploy.sh <dev|test|prod>`. La usan GitHub Actions (`DESTINO=azure`), Azure DevOps y Jenkins, y también puede ejecutarse a mano.

### 7.1 Qué hace `deploy.sh`

| Paso | Acción |
|---|---|
| 1/7 | Crea o reutiliza el grupo de recursos (`RESOURCE_GROUP` o `rg-dataops-<entorno>`) |
| 2/7 | Despliega `infra/arm/infra.json` con `parameters/infra.<entorno>.parameters.json`: Storage ADLS Gen2 (contenedores `raw`, `staging`, `curated`), Key Vault con los secretos y Data Factory con Managed Identity |
| 3/7 | Detiene el trigger para actualizar sin ejecuciones en curso |
| 4/7 | Despliega `infra/arm/adf-content.json`: linked services, datasets, data flow, pipeline y trigger |
| 5/7 | Sube el CSV a `raw/comisiones/` |
| 6/7 | Prueba de humo: ejecuta `pl_comisiones_salario_total` y espera `Succeeded` (`smoke_test_adf.sh`); valida el Parquet en `curated` (`verify_parquet.py`) |
| 7/7 | Activa el trigger (en test queda detenido) |

Los nombres de los recursos incluyen el entorno: `stdataops<entorno>…`, `kv-dataops-<entorno>-…`, `adf-dataops-<entorno>-…`. La plantilla no crea asignaciones de roles, así que basta el rol **Contributor**.

### 7.2 Paso 1 – Preparar Azure (una vez)

```bash
az login
az account show -o table                                   # confirmar la suscripción
az provider register --namespace Microsoft.DataFactory
az provider register --namespace Microsoft.EventGrid       # para el trigger de eventos
```

### 7.3 Paso 2 – Despliegue manual de un entorno

```bash
export PG_PASSWORD='<contraseña>'                 # nunca en el repositorio
export RESOURCE_GROUP='<grupo asignado>'          # opcional
bash scripts/deploy.sh dev                        # luego test y prod
```

### 7.4 Paso 3 – Despliegue desde GitHub Actions

1. Crear una identidad para GitHub con rol Contributor sobre el grupo de recursos (App registration con
   *federated credential* para el repositorio, o un Service Principal):

   ```bash
   az ad sp create-for-rbac --name sp-dataops-github --role Contributor \
     --scopes /subscriptions/<subscription-id>/resourceGroups/<grupo>
   ```

2. En **Settings → Secrets and variables → Actions → Secrets**: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`
   y `AZURE_SUBSCRIPTION_ID`.
3. En **Variables**: `DESTINO = azure` (y `RESOURCE_GROUP` si se usa un único grupo).
4. Hacer push a `develop` o `main`: el mismo CI/CD ejecuta `scripts/deploy.sh` en cada entorno.

### 7.5 Verificación en Azure

* **ADF Studio → Monitor → Pipeline runs:** `pl_comisiones_salario_total` en estado *Succeeded*.
* **Storage → contenedor `curated` → `comisiones/salario_total/periodo=202610/`:** archivo Parquet.

---

## 8. Paso a paso: CI/CD con Azure DevOps y Jenkins

Las tres herramientas llaman al mismo `scripts/deploy.sh`, así que el despliegue es idéntico.

### 8.1 Azure DevOps (`azure-pipelines.yml`)

1. Crear un proyecto en https://dev.azure.com.
2. **Project settings → Service connections → Azure Resource Manager → Workload Identity federation
   (automatic)**, con el nombre **`sc-dataops-comisiones`** y alcance al grupo de recursos o a la suscripción.
3. **Pipelines → Library → Variable group** **`vg-dataops-comisiones`** con `PG_PASSWORD` (secreta) y
   `AZURE_SUBSCRIPTION_ID`.
4. **Pipelines → Environments:** `dataops-dev`, `dataops-test` y `dataops-prod`. En `dataops-prod` →
   *Approvals and checks*: **Approvals** y **Branch control** (solo `refs/heads/main`).
5. **Pipelines → New pipeline → GitHub → Yachiga/dataops-comisiones → Existing YAML** → `/azure-pipelines.yml`.

| Etapa | Cuándo | Qué hace |
|---|---|---|
| CI | todo push y PR a `main`/`develop` | ruff, pytest (JUnit + cobertura), ejecución de prueba, `build_adf_arm.py --check`, `az deployment group validate` |
| CD_DEV | push a `develop` o `main` | `scripts/deploy.sh dev` |
| CD_TEST | después de CD_DEV | `scripts/deploy.sh test` (el trigger queda detenido) |
| CD_PROD | solo `main`, con la aprobación del environment | `scripts/deploy.sh prod` |

### 8.2 Jenkins (`Jenkinsfile`)

El `Jenkinsfile` tiene las mismas etapas (CI → dev → test → aprobación `input` → prod) y el parámetro
`DESTINO` (`local` | `azure`). Necesita la credencial `PG_PASSWORD` (*Secret text*) y un job
*Multibranch Pipeline* apuntando al repositorio. Los pasos completos, con Jenkins en Docker, están en el
README de la versión Jenkins: https://github.com/Yachiga/dataops-comisiones-jenkins

---

## 9. Flujo de trabajo Git

* `main` = producción, `develop` = integración, `feature/*` = cambios.
* Todo cambio entra por **Pull Request** a `develop`. GitHub Actions lo valida y despliega a dev y test; luego se integra con PR `develop → main` y una etiqueta `vX.Y.Z`.
* Versiones publicadas: **v1.0.0** (pipeline y ARM), **v1.1.0** (evidencias) y **v1.2.0** (CI/CD con GitHub Actions).
* Commits con prefijos convencionales: `feat:`, `fix:`, `ci:`, `test:`, `docs:`.
* Si se edita el pipeline en ADF Studio (modo Git), exportar los JSON a `adf/` y ejecutar `python scripts/build_adf_arm.py` antes del commit. Si no, el CI falla.

---

## 10. Resultados esperados y verificación

Estos son los resultados que obtuve con el periodo 202610 y la base real (iguales en dev, test y prod):

| Indicador | Valor |
|---|---|
| Empleados extraídos de PostgreSQL | 48 |
| Filas del CSV | 34 |
| Empleados con comisión | 33 |
| Empleados sin comisión | 15 (`salario_total = mnt_salario`) |
| Comisión del CSV sin empleado | `empleado_id` 4 (reportado, no se carga) |
| Comisiones sobre el tope | 13 (marcadas en `supera_tope_comision`) |
| Σ salario | 138,043.40 |
| Σ comisión aplicada | 342,000.00 |
| Σ salario_total | 480,043.40 |

`verify_parquet.py` comprueba que `salario_total = mnt_salario + mnt_comision` en todas las filas, que no haya `empleado_id` duplicados y que la comisión aplicada no supere la del CSV.

---

## 11. Seguridad

* Ninguna contraseña está en el repositorio. `PG_PASSWORD` es un *secret* de GitHub (y una variable
  secreta en Azure DevOps o Key Vault en Azure); GitHub la enmascara en los logs (`***`).
* `.env` está en `.gitignore`; solo se versiona `.env.example` sin valores.
* `config.py` oculta la contraseña al imprimir la configuración.
* La prueba `test_no_hay_secretos_en_el_repositorio` falla si aparece un secreto en el código.
* Data Factory lee de Key Vault la contraseña de PostgreSQL y la clave del Storage mediante su Managed Identity.
* Producción está protegida: solo se despliega desde `main` y con revisor obligatorio.

---

## 12. Solución de problemas

Varios de estos errores me salieron mientras armaba el proyecto; los dejo con su solución:

| Síntoma | Causa | Solución |
|---|---|---|
| CD falla con "Falta el secret PG_PASSWORD" | El secret no existe o tiene otro nombre | Crearlo como `PG_PASSWORD` (6.3) |
| CI falla en "Lint (ruff)" | Observaciones de estilo en el código | `ruff check --fix src tests scripts`; la versión de ruff está fijada en `requirements-dev.txt` |
| Pruebas de YAML omitidas (*skipped*) | Falta PyYAML | Ya está en `requirements-dev.txt` |
| CD - prod queda en *Waiting* | Falta la aprobación del environment `prod` | **Review deployments → Approve and deploy** (6.7) |
| CD - prod no aparece | La ejecución es de `develop` o de un PR | Producción solo se despliega desde `main` |
| CI falla en `build_adf_arm.py --check` | Se cambió `adf/` sin regenerar la plantilla | `python scripts/build_adf_arm.py` y commit |
| `AuthorizationFailed` o "No subscriptions found" en Azure | La cuenta no tiene acceso a la suscripción o el rol Contributor | Pedir acceso al administrador; mientras tanto usar `DESTINO=local` |
| `Copiar_Empleados_PostgreSQL` falla por timeout en ADF | El servidor PostgreSQL no admite la IP del Azure IR | Usar un Self-hosted IR o pedir apertura del firewall |

---

## 13. Lo que aprendí

* Separar el código del flujo (`src/`, `adf/`) de la infraestructura (`infra/arm/`) y del CI/CD
  (`.github/workflows/`, `azure-pipelines.yml`, `Jenkinsfile`) hace que cada parte se pueda probar por separado.
* Escribir el despliegue una sola vez (`scripts/deploy.sh`) me permitió cambiar de herramienta de CI/CD
  sin rehacer el trabajo cuando perdí el acceso a Azure.
* El CI me detuvo varias veces antes de integrar (lint, pruebas omitidas, secret faltante), y eso es justo lo que se espera de él.
* Las contraseñas nunca deben ir en el repositorio: se guardan como secrets y se ocultan en los logs.

*Trabajo realizado por Yvan Chirinos para el curso DE – DataOps de DMC, noviembre de 2026.*
