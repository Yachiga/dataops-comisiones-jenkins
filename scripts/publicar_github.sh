#!/usr/bin/env bash
# Publica el repositorio local en GitHub con todas sus ramas y etiquetas.
# Antes: crear el repositorio VACÍO en https://github.com/new (sin README ni .gitignore).
# Uso: bash scripts/publicar_github.sh [usuario] [repositorio]
set -euo pipefail
USUARIO="${1:-yachiga}"
REPO="${2:-dataops-comisiones}"
URL="https://github.com/$USUARIO/$REPO.git"

git remote remove origin 2>/dev/null || true
git remote add origin "$URL"
echo "Publicando en $URL (GitHub pedirá usuario y un Personal Access Token como contraseña)"
git push -u origin main
git push origin develop
git push origin --tags
git remote -v
echo "Listo: https://github.com/$USUARIO/$REPO"
