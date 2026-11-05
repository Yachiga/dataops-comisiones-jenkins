# Proyecto DataOps · Cálculo del salario total con comisiones

**Curso:** DE – DataOps (DMC) · Asignación Proyecto 60%  
**Tema:** Proyecto DataOps con Azure DevOps y Azure Data Factory  
**Alumno:** Yvan Chirinos · **Docente:** Miguel Ángel García

> En esta versión el CI/CD corre en **Jenkins** (`Jenkinsfile`); los workflows de GitHub Actions están desactivados.
> Hice también una versión con GitHub Actions: https://github.com/Yachiga/dataops-comisiones

## Sobre este proyecto

Este repositorio es mi solución a la asignación del curso. El caso es un cliente que quiere calcular
cada mes el salario total de sus empleados juntando la tabla `dmc.rrhh.empleado` (PostgreSQL) con un
CSV de comisiones, y que ese flujo se despliegue solo, de desarrollo a producción, con CI/CD.

Lo que construí:

* Un **pipeline en Python** que extrae los empleados de PostgreSQL, lee el CSV, hace el Join por
  `empleado_id`, calcula `salario_total` y genera un **Parquet**. Es el que se ejecuta en los tres entornos.
* El **mismo flujo en Azure Data Factory** (copy, validación, data flow y trigger), con **plantillas ARM**
  para desplegar el Storage, el Key Vault y el Data Factory por entorno.
* Un **CI/CD en Jenkins** que, en cada cambio, corre el lint, las 58 pruebas y la validación de las
  plantillas, y luego despliega a **dev → test → prod**. Producción solo se despliega con aprobación.

Elegí Jenkins porque el enunciado lo permite como alternativa a Azure DevOps, y porque pude
levantarlo en mi equipo con Docker. La cuenta de Azure del curso no tenía suscripciones
disponibles, así que el pipeline de Data Factory y las plantillas ARM quedaron listos y validados,
pero no desplegados. En la [sección 7](#7-paso-a-paso-despliegue-en-azure-arm--data-factory) explico cómo
desplegarlos cuando haya acceso.

## Índice

0. [Sobre este proyecto](#sobre-este-proyecto)
1. [Objetivo](#1-objetivo)
2. [Contenido del repositorio](#2-contenido-del-repositorio)
3. [Arquitectura y flujo de datos](#3-arquitectura-y-flujo-de-datos)
4. [Requisitos previos](#4-requisitos-previos)
5. [Paso a paso: ejecución local](#5-paso-a-paso-ejecución-local)
6. [Paso a paso: despliegue con Jenkins (dev → test → prod)](#6-paso-a-paso-despliegue-con-jenkins-dev--test--prod)
7. [Paso a paso: despliegue en Azure (ARM + Data Factory)](#7-paso-a-paso-despliegue-en-azure-arm--data-factory)
8. [Otras herramientas de CI/CD incluidas](#8-otras-herramientas-de-cicd-incluidas)
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
| **Script Python** | `src/comisiones/` | Lo ejecuta Jenkins en cada entorno (`DESTINO=local`), en local y en las pruebas |
| **Azure Data Factory** | `adf/` → `infra/arm/adf-content.json` | Despliegue en Azure (`DESTINO=azure`) con plantillas ARM |

---

## 2. Contenido del repositorio

```
dataops-comisiones-jenkins/
├── Jenkinsfile                     # CI/CD: CI → CD dev → CD test → aprobación → CD prod
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
├── docs/                                        # diagramas de arquitectura (flujo y CI/CD)
├── sql/extract_empleado.sql                     # consulta de extracción
├── azure-pipelines.yml + cicd/templates/        # alternativa Azure DevOps (no activa aquí)
└── .github/workflows/                           # alternativa GitHub Actions (desactivada aquí)
```

---

## 3. Arquitectura y flujo de datos

### 3.1 Flujo con Python (lo que ejecuta Jenkins)

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
| Python | 3.10 o superior | ejecución local y en el agente Jenkins |
| Docker Desktop | cualquiera | levantar Jenkins en el equipo |
| Acceso a PostgreSQL | usuario de solo lectura `usr_ro_dmc_rrhh_estudiantes` | extraer `rrhh.empleado` |
| Cuenta de GitHub | — | alojar el repositorio que lee Jenkins |
| Suscripción de Azure + Azure CLI | solo para `DESTINO=azure` | desplegar ARM y Data Factory |

---

## 5. Paso a paso: ejecución local

Así lo ejecuto en mi equipo antes de subir cambios:

**Paso 1 – Clonar el repositorio**

```bash
git clone https://github.com/Yachiga/dataops-comisiones-jenkins.git
cd dataops-comisiones-jenkins
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

## 6. Paso a paso: despliegue con Jenkins (dev → test → prod)

### 6.1 Cómo funciona

```
feature/*  ──PR──►  develop  ──PR──►  main
                      │                 │
                      ▼                 ▼
               CI → CD dev →     CI → CD dev → CD test → Aprobación → CD prod
                    CD test
```

| # | Etapa | Ramas | Qué hace | Si falla |
|---|---|---|---|---|
| 1 | Preparar entorno Python | todas | crea `.venv` e instala `requirements-dev.txt` | se detiene |
| 2 | CI - Lint | todas | `ruff check src tests scripts` | se detiene |
| 3 | CI - Pruebas | todas | 58 pruebas pytest; publica el reporte JUnit en *Tests* | se detiene |
| 4 | CI - Validar artefactos ADF / ARM | todas | `build_adf_arm.py --check` | se detiene |
| 5 | CI - Ejecución de prueba (fixture) | todas | corre el pipeline con datos de prueba; archiva `output/ci/` | se detiene |
| 6 | CD - dev | develop, main | pipeline contra PostgreSQL → `datalake/dev/` + validación | no despliega test ni prod |
| 7 | CD - test | develop, main | lo mismo en `datalake/test/` | no despliega prod |
| 8 | Aprobación producción | main | paso `input` "¿Desplegar a PRODUCCIÓN?" (espera 30 min) | sin aprobación no hay prod |
| 9 | CD - prod | main | lo mismo en `datalake/prod/` | — |

Parámetros del job:

| Parámetro | Valor por defecto | Descripción |
|---|---|---|
| `DESTINO` | `local` | `local` = pipeline Python con Parquet en `datalake/<entorno>/` (artefacto de Jenkins); `azure` = ARM + Data Factory con `scripts/deploy.sh` |
| `CSV_FILE` | `ComisionEmpleados_V1_202610.csv` | CSV dentro de `data/input/` |
| `RESOURCE_GROUP` | vacío | solo `azure`: vacío = `rg-dataops-<entorno>` |

### 6.2 Paso 1 – Levantar Jenkins con Docker

Yo lo levanté en Windows con Docker Desktop. En PowerShell:

```powershell
docker run -d --name jenkins-dataops -p 8090:8080 -u root `
  -v jenkins_dataops:/var/jenkins_home jenkins/jenkins:lts-jdk17
```

* `-p 8090:8080`: Jenkins queda en http://localhost:8090.
* `-v jenkins_dataops:/var/jenkins_home`: la configuración y el historial sobreviven a reinicios.

### 6.3 Paso 2 – Instalar Python dentro del contenedor

```powershell
docker exec jenkins-dataops bash -c "apt-get update && apt-get install -y python3 python3-venv python3-pip"
docker exec jenkins-dataops python3 --version      # debe mostrar 3.10 o superior
```

### 6.4 Paso 3 – Configuración inicial de Jenkins

1. Obtener la clave inicial:

   ```powershell
   docker exec jenkins-dataops cat /var/jenkins_home/secrets/initialAdminPassword
   ```

2. Abrir http://localhost:8090 y pegar la clave.
3. Elegir **Install suggested plugins**. Incluyen *Pipeline*, *Git*, *Credentials Binding*, *JUnit*, *Timestamper* y *Branch API* (Multibranch), que usa el `Jenkinsfile`.
4. Crear el usuario administrador y confirmar la URL `http://localhost:8090/`.

### 6.5 Paso 4 – Crear la credencial de la base de datos

1. **Manage Jenkins → Credentials → System → Global credentials (unrestricted) → Add Credentials**.
2. Completar:
   * **Kind:** `Secret text`
   * **Secret:** contraseña del usuario `usr_ro_dmc_rrhh_estudiantes`
   * **ID:** `PG_PASSWORD` (debe ser exactamente este, porque el `Jenkinsfile` lo busca por ese ID)
   * **Description:** `Contraseña PostgreSQL dmc`
3. **Create**.

Solo para `DESTINO=azure` hacen falta dos credenciales más:

| ID | Tipo | Valor |
|---|---|---|
| `azure-sp` | Username with password | usuario = `appId` del Service Principal, contraseña = su secreto |
| `azure-tenant-id` | Secret text | ID del tenant de Azure |

### 6.6 Paso 5 – Crear el job Multibranch Pipeline

1. **Dashboard → New Item**, nombre `dataops-comisiones`, tipo **Multibranch Pipeline** → **OK**.
2. **Branch Sources → Add source → Git**:
   * **Project Repository:** `https://github.com/Yachiga/dataops-comisiones-jenkins.git`
   * **Credentials:** ninguna (el repositorio es público).
3. **Build Configuration:** *by Jenkinsfile*, **Script Path** `Jenkinsfile`.
4. **Scan Multibranch Pipeline Triggers:** marcar *Periodically if not otherwise run* → **Interval** `1 minute`.
5. **Save**. Jenkins escanea el repositorio y crea un job por rama (`develop` y `main`).

### 6.7 Paso 6 – Ejecutar el CI/CD

* **Automático:** cada push a `develop` o `main` se detecta en un máximo de 1 minuto y se lanza el build.
* **Manual:** abrir la rama → **Build with Parameters** → `DESTINO = local` → **Build**.

> La primera ejecución de cada rama solo registra los parámetros. Si aparece solo **Build Now**, ejecutarla una vez; luego aparece **Build with Parameters**.

### 6.8 Paso 7 – Aprobar el paso a producción (rama main)

Cuando el build de `main` llega a **Aprobación producción** queda en pausa:

1. Abrir el build (por ejemplo `main #5`) → etapa **Aprobación producción**.
2. Revisar los logs de **CD - dev** y **CD - test**.
3. Pulsar **Desplegar**. Jenkins registra el aprobador ("Approved by …").
4. Si nadie aprueba en 30 minutos, el build termina como **ABORTED** y producción no se despliega.

### 6.9 Paso 8 – Verificar el despliegue en cada entorno

| Qué revisar | Dónde | Resultado esperado |
|---|---|---|
| Estado del build | página del job / vista *Stages* | todas las etapas en verde, `SUCCESS` |
| Log de cada entorno | etapa **CD - dev / test / prod** → log | `Empleados extraídos de PostgreSQL: 48 filas`, `"estado": "Succeeded"`, `OK: Parquet validado` |
| Pruebas | pestaña **Tests** | 58 aprobadas, 0 fallidas |
| Archivos generados | **Artifacts** | `datalake/dev/`, `datalake/test/`, `datalake/prod/` con `salario_total_202610.parquet`, `.xlsx`, `.csv` y `reporte_ejecucion.json` |
| Aprobación | etapa **Aprobación producción** | "Approved by <usuario>" |

### 6.10 Comandos útiles del contenedor

```powershell
docker stop jenkins-dataops      # detener
docker start jenkins-dataops     # volver a iniciar (conserva la configuración)
docker logs -f jenkins-dataops   # ver el log de Jenkins
```

---

## 7. Paso a paso: despliegue en Azure (ARM + Data Factory)

Toda la lógica está en `scripts/deploy.sh <dev|test|prod>`. La usan Jenkins (`DESTINO=azure`), Azure DevOps y GitHub Actions, y también puede ejecutarse a mano.

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

### 7.4 Paso 3 – Despliegue desde Jenkins

1. Crear un Service Principal con rol Contributor sobre el grupo de recursos:

   ```bash
   az ad sp create-for-rbac --name sp-dataops-jenkins --role Contributor \
     --scopes /subscriptions/<subscription-id>/resourceGroups/<grupo>
   ```

2. Registrar `azure-sp` y `azure-tenant-id` en Jenkins (ver 6.5).
3. Instalar Azure CLI en el contenedor:

   ```powershell
   docker exec jenkins-dataops bash -c "curl -sL https://aka.ms/InstallAzureCLIDeb | bash"
   ```

4. **Build with Parameters** → `DESTINO = azure` (y `RESOURCE_GROUP` si aplica).

### 7.5 Verificación en Azure

* **ADF Studio → Monitor → Pipeline runs:** `pl_comisiones_salario_total` en estado *Succeeded*.
* **Storage → contenedor `curated` → `comisiones/salario_total/periodo=202610/`:** archivo Parquet.

---

## 8. Otras herramientas de CI/CD incluidas

Las tres herramientas llaman al mismo `scripts/deploy.sh`, así que el despliegue es idéntico.

* **Azure DevOps** (`azure-pipelines.yml` + `cicd/templates/deploy-env.yml`): etapas CI → CD_DEV → CD_TEST → CD_PROD. Requiere la service connection `sc-dataops-comisiones`, el variable group `vg-dataops-comisiones` (`PG_PASSWORD` secreta) y los environments `dataops-dev`, `dataops-test` y `dataops-prod` (este último con aprobación y *Branch control* a `main`).
* **GitHub Actions** (`.github/workflows/ci-cd.yml` + `deploy.yml`): desactivado en este repositorio. Está activo en la versión https://github.com/Yachiga/dataops-comisiones.

---

## 9. Flujo de trabajo Git

* `main` = producción, `develop` = integración, `feature/*` = cambios.
* Todo cambio entra por **Pull Request** a `develop`. Jenkins lo valida en dev y test, y luego se integra con PR `develop → main` y una etiqueta `vX.Y.Z` (versión actual: **v2.0.0**).
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

* Ninguna contraseña está en el repositorio. `PG_PASSWORD` vive en el almacén de credenciales de Jenkins (y en Key Vault en Azure), y Jenkins la enmascara en los logs (`****`).
* `.env` está en `.gitignore`; solo se versiona `.env.example` sin valores.
* `config.py` oculta la contraseña al imprimir la configuración.
* La prueba `test_no_hay_secretos_en_el_repositorio` falla si aparece un secreto en el código.
* Data Factory lee de Key Vault la contraseña de PostgreSQL y la clave del Storage mediante su Managed Identity.

---

## 12. Solución de problemas

Varios de estos errores me salieron mientras armaba el proyecto; los dejo con su solución:

| Síntoma | Causa | Solución |
|---|---|---|
| `python3: not found` en *Preparar entorno Python* | Python no está instalado en el contenedor | Ejecutar el paso 6.3 |
| `Falta la variable de entorno obligatoria: PG_PASSWORD` o error de autenticación en CD - dev | La credencial no existe o su ID es distinto | Crear la credencial con ID exacto `PG_PASSWORD` (6.5) |
| `Could not find credentials entry with ID 'azure-sp'` | El build tomó `DESTINO=azure` de una ejecución anterior | **Build with Parameters** con `DESTINO = local`, o crear las credenciales de Azure |
| Build `ABORTED` en *Aprobación producción* | Nadie aprobó en 30 minutos | Volver a ejecutar y aprobar a tiempo |
| No aparece **Build with Parameters** | Primera ejecución de la rama | Ejecutar **Build Now** una vez |
| Jenkins no detecta los cambios | El escaneo periódico no está activo | Activar el intervalo de 1 minuto (6.6) o pulsar **Scan Multibranch Pipeline Now** |
| CI falla en `build_adf_arm.py --check` | Se cambió `adf/` sin regenerar la plantilla | `python scripts/build_adf_arm.py` y commit |
| `AuthorizationFailed` o "No subscriptions found" en Azure | La cuenta no tiene acceso a la suscripción o el rol Contributor | Pedir acceso al administrador; mientras tanto usar `DESTINO=local` |
| `Copiar_Empleados_PostgreSQL` falla por timeout en ADF | El servidor PostgreSQL no admite la IP del Azure IR | Usar un Self-hosted IR o pedir apertura del firewall |

---

## 13. Lo que aprendí

* Separar el código del flujo (`src/`, `adf/`) de la infraestructura (`infra/arm/`) y del CI/CD (`Jenkinsfile`)
  hace que cada cambio se pueda probar por separado.
* Las pruebas automáticas y la aprobación manual antes de producción evitan que un error llegue al
  entorno final: en mis ejecuciones, cuando algo fallaba el pipeline se detenía y no avanzaba.
* Las contraseñas nunca deben ir en el repositorio: Jenkins las guarda como credenciales y las oculta en los logs.

*Trabajo realizado por Yvan Chirinos para el curso DE – DataOps de DMC, noviembre de 2026.*
