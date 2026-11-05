#!/usr/bin/env bash
# =============================================================================
# Despliegue completo de un entorno (dev | test | prod) con Azure CLI.
# Lo usan Azure DevOps, Jenkins y GitHub Actions, y también puede ejecutarse a
# mano después de "az login" (útil para cuentas de laboratorio con MFA).
#
# Uso:
#   export PG_PASSWORD='...'                  # nunca en el repositorio
#   bash scripts/deploy.sh dev
#
# Variables opcionales:
#   RESOURCE_GROUP   grupo de recursos (por defecto rg-dataops-<entorno>).
#                    Si tu cuenta solo tiene un grupo asignado, usa ese mismo
#                    para los tres entornos: los nombres de recursos ya llevan
#                    el entorno.
#   LOCATION         región (por defecto eastus2)
#   CSV_FILE         nombre del CSV (por defecto ComisionEmpleados_V1_202610.csv)
#   PERIODO          AAAAMM (por defecto se toma del nombre del CSV)
#   SKIP_SMOKE=1     no ejecutar el pipeline ADF tras desplegar
# =============================================================================
set -euo pipefail

ENTORNO="${1:?Indique el entorno: dev | test | prod}"
case "$ENTORNO" in dev|test|prod) ;; *) echo "Entorno no válido: $ENTORNO"; exit 2 ;; esac
: "${PG_PASSWORD:?Defina la variable de entorno PG_PASSWORD}"

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RG="${RESOURCE_GROUP:-rg-dataops-$ENTORNO}"
LOCATION="${LOCATION:-eastus2}"
CSV_FILE="${CSV_FILE:-ComisionEmpleados_V1_202610.csv}"
PERIODO="${PERIODO:-$(echo "$CSV_FILE" | sed -E 's/.*_([0-9]{6})(_[0-9]+)?\.csv$/\1/')}"
DEPLOY_NAME="dataops-$ENTORNO-$(date +%Y%m%d%H%M%S)"

paso() { echo; echo "==================== $* ===================="; }

paso "1/7 Grupo de recursos $RG ($ENTORNO)"
if az group show -n "$RG" -o none 2>/dev/null; then
  echo "El grupo $RG ya existe"
else
  az group create -n "$RG" -l "$LOCATION" -o table
fi

paso "2/7 ARM infraestructura: Storage ADLS Gen2 + Key Vault + Data Factory"
OUT=$(az deployment group create -g "$RG" -n "$DEPLOY_NAME-infra" \
  --template-file "$RAIZ/infra/arm/infra.json" \
  --parameters @"$RAIZ/infra/arm/parameters/infra.$ENTORNO.parameters.json" \
  --parameters pgPassword="$PG_PASSWORD" \
  --query properties.outputs -o json)
salida() { echo "$OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['$1']['value'])"; }
ADF=$(salida factoryName); ST=$(salida storageAccountName); DFS=$(salida dfsEndpoint)
SAID=$(salida storageAccountId); KV=$(salida keyVaultUri)
echo "Data Factory : $ADF"; echo "Storage      : $ST"; echo "Key Vault    : $KV"

az extension add -n datafactory --upgrade -y -o none 2>/dev/null || true

paso "3/7 Detener trigger antes de actualizar"
az datafactory trigger stop -g "$RG" --factory-name "$ADF" --name tr_blob_nuevo_csv_comisiones -o none 2>/dev/null \
  || echo "El trigger aún no existe (primer despliegue)"

paso "4/7 ARM contenido de Data Factory"
az deployment group create -g "$RG" -n "$DEPLOY_NAME-adf" \
  --template-file "$RAIZ/infra/arm/adf-content.json" \
  --parameters factoryName="$ADF" entorno="$ENTORNO" keyVaultUri="$KV" \
               dfsEndpoint="$DFS" storageAccountId="$SAID" \
  --query "{estado:properties.provisioningState, recursos:properties.outputs.recursos.value}" -o table

paso "5/7 Cargar CSV a raw/comisiones/$CSV_FILE"
KEY=$(az storage account keys list -g "$RG" -n "$ST" --query "[0].value" -o tsv)
az storage blob upload --account-name "$ST" --account-key "$KEY" --overwrite \
  -c raw -n "comisiones/$CSV_FILE" -f "$RAIZ/data/input/$CSV_FILE" -o table

if [ "${SKIP_SMOKE:-0}" != "1" ]; then
  paso "6/7 Prueba de humo: ejecutar pl_comisiones_salario_total"
  bash "$RAIZ/scripts/smoke_test_adf.sh" "$RG" "$ADF" "$CSV_FILE" "$PERIODO" "$ENTORNO"

  paso "6b/7 Validar Parquet en curated"
  python3 -m pip install -q pandas pyarrow azure-storage-file-datalake azure-identity >/dev/null
  AZURE_STORAGE_KEY="$KEY" python3 "$RAIZ/scripts/verify_parquet.py" \
    --account "$ST" --periodo "$PERIODO" --csv "$RAIZ/data/input/$CSV_FILE"
fi

paso "7/7 Trigger de eventos"
if [ "$ENTORNO" = "test" ]; then
  echo "En test el trigger queda detenido"
else
  az datafactory trigger start -g "$RG" --factory-name "$ADF" --name tr_blob_nuevo_csv_comisiones -o none \
    && echo "Trigger activo" \
    || echo "AVISO: no se pudo activar el trigger (registre el proveedor Microsoft.EventGrid)"
fi

echo; echo "Despliegue de $ENTORNO completado: $ADF / $ST"
