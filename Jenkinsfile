// =============================================================================
// CI/CD DataOps - Comisiones de empleados (Jenkins, alternativa a Azure DevOps)
//
// Requisitos en el agente: python3 (>=3.10) con venv, git y, para DESTINO=azure, Azure CLI.
// Credenciales en Jenkins (Manage Jenkins > Credentials):
//   pg-password          (Secret text)  contraseña del usuario PostgreSQL de solo lectura
//   azure-sp             (Username with password) appId / secret del Service Principal  [solo DESTINO=azure]
//   azure-tenant-id      (Secret text)                                                   [solo DESTINO=azure]
//
// DESTINO=azure : despliega ARM + Data Factory en Azure con scripts/deploy.sh
// DESTINO=local : ejecuta el pipeline Python por entorno y publica el Parquet en
//                 datalake/<entorno>/ (sin Azure; útil si no hay permisos en la suscripción)
// =============================================================================
pipeline {
    agent any

    parameters {
        choice(name: 'DESTINO', choices: ['azure', 'local'], description: 'Dónde desplegar')
        string(name: 'CSV_FILE', defaultValue: 'ComisionEmpleados_V1_202610.csv', description: 'CSV en data/input/')
        string(name: 'RESOURCE_GROUP', defaultValue: '', description: 'Vacío = rg-dataops-<entorno>; o un único grupo para los tres entornos')
    }

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        PYTHONPATH = "${WORKSPACE}/src"
        VENV       = "${WORKSPACE}/.venv"
    }

    stages {
        stage('Preparar entorno Python') {
            steps {
                sh '''
                    python3 -m venv "$VENV"
                    . "$VENV/bin/activate"
                    pip install -q --upgrade pip
                    pip install -q -r requirements-dev.txt
                '''
            }
        }

        stage('CI - Lint') {
            steps {
                sh '. "$VENV/bin/activate" && ruff check src tests scripts'
            }
        }

        stage('CI - Pruebas') {
            steps {
                sh '. "$VENV/bin/activate" && python -m pytest --junitxml=reports/junit.xml --cov=src/comisiones --cov-report=xml:reports/coverage.xml'
            }
            post {
                always { junit 'reports/junit.xml' }
            }
        }

        stage('CI - Validar artefactos ADF / ARM') {
            steps {
                sh '. "$VENV/bin/activate" && python scripts/build_adf_arm.py --check'
            }
        }

        stage('CI - Ejecución de prueba (fixture)') {
            steps {
                sh '''
                    . "$VENV/bin/activate"
                    python -m comisiones.pipeline --modo local --entorno dev \
                        --empleados-file tests/fixtures/empleados_fixture.csv \
                        --csv "data/input/${CSV_FILE}" --salida output/ci
                '''
                archiveArtifacts artifacts: 'output/ci/**', fingerprint: true
            }
        }

        stage('CD - dev') {
            when { anyOf { branch 'develop'; branch 'main' } }
            steps { script { desplegar('dev') } }
        }

        stage('CD - test') {
            when { anyOf { branch 'develop'; branch 'main' } }
            steps { script { desplegar('test') } }
        }

        stage('Aprobación producción') {
            when { branch 'main' }
            steps {
                timeout(time: 30, unit: 'MINUTES') {
                    input message: '¿Desplegar a PRODUCCIÓN?', ok: 'Desplegar',
                          submitterParameter: 'APROBADOR'
                }
            }
        }

        stage('CD - prod') {
            when { branch 'main' }
            steps { script { desplegar('prod') } }
        }
    }

    post {
        success { echo "Pipeline OK - rama ${env.BRANCH_NAME ?: 'local'} - destino ${params.DESTINO}" }
        failure { echo 'Pipeline con errores: revisar la etapa marcada en rojo' }
    }
}

// -----------------------------------------------------------------------------
def desplegar(String entorno) {
    if (params.DESTINO == 'azure') {
        withCredentials([
            string(credentialsId: 'pg-password', variable: 'PG_PASSWORD'),
            usernamePassword(credentialsId: 'azure-sp', usernameVariable: 'AZ_CLIENT_ID', passwordVariable: 'AZ_CLIENT_SECRET'),
            string(credentialsId: 'azure-tenant-id', variable: 'AZ_TENANT_ID')
        ]) {
            withEnv(["RESOURCE_GROUP=${params.RESOURCE_GROUP ?: 'rg-dataops-' + entorno}", "CSV_FILE=${params.CSV_FILE}"]) {
                sh '''
                    . "$VENV/bin/activate"
                    az login --service-principal -u "$AZ_CLIENT_ID" -p "$AZ_CLIENT_SECRET" --tenant "$AZ_TENANT_ID" -o none
                '''
                sh "bash scripts/deploy.sh ${entorno}"
            }
        }
    } else {
        withCredentials([string(credentialsId: 'pg-password', variable: 'PG_PASSWORD')]) {
            sh """
                . "\$VENV/bin/activate"
                export PG_HOST=mgg.vps.webdock.cloud PG_USER=usr_ro_dmc_rrhh_estudiantes PG_DATABASE=dmc
                python -m comisiones.pipeline --modo local --entorno ${entorno} \
                    --csv "data/input/${params.CSV_FILE}" --salida datalake/${entorno} \
                    --formatos parquet xlsx
            """
        }
        archiveArtifacts artifacts: "datalake/${entorno}/**", fingerprint: true
    }
}
