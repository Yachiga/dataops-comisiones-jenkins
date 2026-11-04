"""Configuración del pipeline por entorno (dev / test / prod).

Toda la configuración sensible se lee de variables de entorno; en Azure DevOps
se inyectan desde un Variable Group enlazado a Key Vault. Nunca se versionan
contraseñas en el repositorio.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

ENTORNOS_VALIDOS = ("dev", "test", "prod")


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    schema: str = "rrhh"
    table: str = "empleado"
    sslmode: str = "prefer"

    @property
    def url(self) -> str:
        from urllib.parse import quote_plus

        return (
            f"postgresql+psycopg2://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.database}?sslmode={self.sslmode}"
        )


@dataclass(frozen=True)
class StorageConfig:
    account_name: str | None
    account_key: str | None = field(default=None, repr=False)
    connection_string: str | None = field(default=None, repr=False)
    raw_container: str = "raw"
    curated_container: str = "curated"
    csv_blob: str = "comisiones/ComisionEmpleados_V1_202610.csv"
    output_dir: str = "comisiones/salario_total"


@dataclass(frozen=True)
class PipelineConfig:
    entorno: str
    postgres: PostgresConfig | None
    storage: StorageConfig


def _env(nombre: str, defecto: str | None = None, obligatorio: bool = False) -> str | None:
    valor = os.getenv(nombre, defecto)
    if obligatorio and not valor:
        raise EnvironmentError(f"Falta la variable de entorno obligatoria: {nombre}")
    return valor


def cargar_config(entorno: str | None = None, requiere_postgres: bool = True) -> PipelineConfig:
    entorno = (entorno or _env("PIPELINE_ENV", "dev")).lower()
    if entorno not in ENTORNOS_VALIDOS:
        raise ValueError(f"Entorno '{entorno}' no válido. Use uno de {ENTORNOS_VALIDOS}")

    pg = None
    if requiere_postgres:
        pg = PostgresConfig(
            host=_env("PG_HOST", obligatorio=True),
            port=int(_env("PG_PORT", "5432")),
            database=_env("PG_DATABASE", "dmc"),
            user=_env("PG_USER", obligatorio=True),
            password=_env("PG_PASSWORD", obligatorio=True),
            schema=_env("PG_SCHEMA", "rrhh"),
            table=_env("PG_TABLE", "empleado"),
            sslmode=_env("PG_SSLMODE", "prefer"),
        )

    storage = StorageConfig(
        account_name=_env("STORAGE_ACCOUNT_NAME"),
        account_key=_env("STORAGE_ACCOUNT_KEY"),
        connection_string=_env("AZURE_STORAGE_CONNECTION_STRING"),
        raw_container=_env("RAW_CONTAINER", "raw"),
        curated_container=_env("CURATED_CONTAINER", "curated"),
        csv_blob=_env("CSV_BLOB", "comisiones/ComisionEmpleados_V1_202610.csv"),
        output_dir=_env("OUTPUT_DIR", "comisiones/salario_total"),
    )
    return PipelineConfig(entorno=entorno, postgres=pg, storage=storage)
