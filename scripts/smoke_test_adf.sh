#!/usr/bin/env bash
# Prueba de humo: lanza el pipeline de ADF y espera a que termine.
# Uso: smoke_test_adf.sh <resource-group> <factory-name> <csv-file> <periodo> <entorno>
set -euo pipefail
RG="$1"; ADF="$2"; CSV="$3"; PERIODO="$4"; ENTORNO="$5"
PIPELINE="pl_comisiones_salario_total"

az extension add -n datafactory --upgrade -y -o none
echo ">> Lanzando $PIPELINE en $ADF (periodo=$PERIODO, entorno=$ENTORNO)"
RUN_ID=$(az datafactory pipeline create-run -g "$RG" --factory-name "$ADF" --name "$PIPELINE" \
  --parameters "{\"csvFileName\":\"$CSV\",\"periodo\":\"$PERIODO\",\"entorno\":\"$ENTORNO\"}" \
  --query runId -o tsv)
echo ">> runId=$RUN_ID"

for i in $(seq 1 60); do
  STATUS=$(az datafactory pipeline-run show -g "$RG" --factory-name "$ADF" --run-id "$RUN_ID" --query status -o tsv)
  echo "   [$(date +%H:%M:%S)] estado=$STATUS"
  case "$STATUS" in
    Succeeded) break ;;
    Failed|Cancelled)
      az datafactory activity-run query-by-pipeline-run -g "$RG" --factory-name "$ADF" --run-id "$RUN_ID" \
        --last-updated-after "$(date -u -d '-2 hours' +%Y-%m-%dT%H:%M:%SZ)" \
        --last-updated-before "$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)" \
        --query "value[].{actividad:activityName,estado:status,error:error.message}" -o table
      exit 1 ;;
  esac
  sleep 20
done
[ "$STATUS" = "Succeeded" ] || { echo "Tiempo de espera agotado"; exit 1; }

echo ">> Detalle de actividades"
az datafactory activity-run query-by-pipeline-run -g "$RG" --factory-name "$ADF" --run-id "$RUN_ID" \
  --last-updated-after "$(date -u -d '-2 hours' +%Y-%m-%dT%H:%M:%SZ)" \
  --last-updated-before "$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)" \
  --query "value[].{actividad:activityName,tipo:activityType,estado:status,duracionMs:durationInMs}" -o table
echo "##vso[task.setvariable variable=adfRunId]$RUN_ID"
