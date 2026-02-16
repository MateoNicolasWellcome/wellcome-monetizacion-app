"""
Módulo de almacenamiento multi-tenant para el portal Wellcome.

Cada cliente tiene su propio directorio de datos bajo DATA_ROOT/{client_id}/.

Uso típico:

    from services.storage import load_csv, save_csv, get_path

    df = load_csv("monetizaciones.csv", "wellcome_bogota")
    # ... modificaciones ...
    save_csv("monetizaciones.csv", df, "wellcome_bogota")
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Iterable, Optional

import pandas as pd


# Raíz del proyecto (services/ está un nivel debajo)
BASE_DIR = Path(__file__).parents[1]

# Carpeta con los CSV "semilla" que vienen en el repo
SEED_DIR = BASE_DIR / "seed_data"

# Posibles ubicaciones para datos
VOLUME_DATA_DIR = Path("/app/data")        # Railway (volume)
LOCAL_DATA_DIR = BASE_DIR / "data"         # Desarrollo local


def _detect_data_root() -> Path:
    """
    Devuelve el directorio raíz de datos.

    Prioridad:
    1) /app/data si existe (Railway con volumen montado).
    2) BASE_DIR/data si no existe el volumen (entorno local).
    """
    if VOLUME_DATA_DIR.exists():
        return VOLUME_DATA_DIR
    return LOCAL_DATA_DIR


# Directorio raíz de datos (los subdirectorios por cliente van debajo)
DATA_ROOT = _detect_data_root()


def get_client_data_dir(client_id: str) -> Path:
    """Devuelve el directorio de datos para un cliente específico."""
    return DATA_ROOT / client_id


def init_client_storage(
    client_id: str,
    seed_dir_name: str = "seed_data",
    seed_filenames: Optional[Iterable[str]] = None,
) -> None:
    """
    Inicializa el almacenamiento para un cliente específico.
    Crea el directorio del cliente y copia archivos semilla si no existen.

    Args:
        client_id: Identificador del cliente (ej: "wellcome_bogota").
        seed_dir_name: Nombre de la carpeta semilla relativa a BASE_DIR.
        seed_filenames: Archivos específicos a copiar, o None para todos.
    """
    client_dir = get_client_data_dir(client_id)
    client_dir.mkdir(parents=True, exist_ok=True)

    seed_dir = BASE_DIR / seed_dir_name
    if not seed_dir.exists():
        return

    if seed_filenames is None:
        seed_filenames = [p.name for p in seed_dir.iterdir() if p.is_file()]

    for fname in seed_filenames:
        src = seed_dir / fname
        dst = client_dir / fname
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)


def migrate_legacy_data(client_id: str) -> None:
    """
    Migración única: mueve archivos planos de DATA_ROOT a DATA_ROOT/{client_id}/
    si existen. Útil para la primera vez que se despliega la versión multi-tenant.
    """
    client_dir = get_client_data_dir(client_id)
    client_dir.mkdir(parents=True, exist_ok=True)

    for f in DATA_ROOT.iterdir():
        if f.is_file() and f.suffix in ('.csv', '.json'):
            dest = client_dir / f.name
            if not dest.exists():
                f.rename(dest)


def get_path(filename: str, client_id: str) -> Path:
    """
    Devuelve el Path absoluto a un archivo de datos dentro del directorio del cliente.

    Ejemplo:
        path = get_path("monetizaciones.csv", "wellcome_bogota")
    """
    return get_client_data_dir(client_id) / filename


def file_exists(filename: str, client_id: str) -> bool:
    """Indica si existe un archivo de datos con ese nombre para el cliente."""
    return get_path(filename, client_id).exists()


def load_csv(filename: str, client_id: str, **read_kwargs) -> pd.DataFrame:
    """
    Carga un CSV desde el directorio del cliente y lo devuelve como DataFrame.

    read_kwargs se pasa directamente a pandas.read_csv.
    """
    path = get_path(filename, client_id)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de datos: {path}")

    return pd.read_csv(path, **read_kwargs)


def save_csv(filename: str, df: pd.DataFrame, client_id: str, **to_csv_kwargs) -> None:
    """
    Guarda un DataFrame como CSV dentro del directorio del cliente.

    Por defecto, index=False a menos que se especifique lo contrario.
    """
    path = get_path(filename, client_id)
    to_csv_kwargs.setdefault("index", False)
    df.to_csv(path, **to_csv_kwargs)


def list_files(client_id: str) -> list[Path]:
    """
    Devuelve una lista de archivos actualmente en el directorio del cliente.
    """
    client_dir = get_client_data_dir(client_id)
    if not client_dir.exists():
        return []
    return [p for p in client_dir.iterdir() if p.is_file()]
