"""
Módulo de almacenamiento para el portal Wellcome.

Se encarga de:
- Detectar el directorio de datos (volume en /app/data o carpeta local /data).
- Inicializar los archivos a partir de /seed_data la primera vez.
- Proveer funciones simples para leer y escribir CSV.

Uso típico:

    from services.storage import load_csv, save_csv, get_path

    df = load_csv("monetizaciones.csv")
    # ... modificaciones ...
    save_csv("monetizaciones.csv", df)
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


def _detect_data_dir() -> Path:
    """
    Devuelve el directorio de datos a usar.

    Prioridad:
    1) /app/data si existe (Railway con volumen montado).
    2) BASE_DIR/data si no existe el volumen (entorno local).
    """
    if VOLUME_DATA_DIR.exists():
        return VOLUME_DATA_DIR
    return LOCAL_DATA_DIR


# Directorio de datos "activo"
DATA_DIR = _detect_data_dir()


def init_storage(seed_filenames: Optional[Iterable[str]] = None) -> None:
    """
    Inicializa el sistema de almacenamiento:

    - Crea DATA_DIR si no existe.
    - Copia archivos desde SEED_DIR a DATA_DIR si aún no existen.
    - Si seed_filenames es None, copia todos los archivos de SEED_DIR.
    """

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not SEED_DIR.exists():
        # No hay semilla, nada que inicializar
        return

    if seed_filenames is None:
        # Tomar todos los archivos del directorio seed_data
        seed_filenames = [p.name for p in SEED_DIR.iterdir() if p.is_file()]

    for fname in seed_filenames:
        src = SEED_DIR / fname
        dst = DATA_DIR / fname

        if not src.exists():
            # Archivo declarado pero no existe en la semilla -> lo ignoramos
            continue

        if not dst.exists():
            shutil.copy(src, dst)


def get_data_dir() -> Path:
    """Devuelve el Path del directorio de datos actual."""
    return DATA_DIR


def get_path(filename: str) -> Path:
    """
    Devuelve el Path absoluto a un archivo de datos dentro de DATA_DIR.

    Ejemplo:
        path = get_path("monetizaciones.csv")
    """
    return DATA_DIR / filename


def file_exists(filename: str) -> bool:
    """Indica si existe un archivo de datos con ese nombre en DATA_DIR."""
    return get_path(filename).exists()


def load_csv(filename: str, **read_kwargs) -> pd.DataFrame:
    """
    Carga un CSV desde DATA_DIR y lo devuelve como DataFrame de pandas.

    read_kwargs se pasa directamente a pandas.read_csv,
    por si quieres especificar encoding, sep, etc.
    """
    path = get_path(filename)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de datos: {path}")

    return pd.read_csv(path, **read_kwargs)


def save_csv(filename: str, df: pd.DataFrame, **to_csv_kwargs) -> None:
    """
    Guarda un DataFrame como CSV dentro de DATA_DIR.

    Por defecto, index=False a menos que se especifique lo contrario.
    """
    path = get_path(filename)
    to_csv_kwargs.setdefault("index", False)
    df.to_csv(path, **to_csv_kwargs)


def list_files() -> list[Path]:
    """
    Devuelve una lista de archivos actualmente en DATA_DIR.
    Útil para depuración o paneles de administración.
    """
    if not DATA_DIR.exists():
        return []
    return [p for p in DATA_DIR.iterdir() if p.is_file()]


# Inicializar storage al importar el módulo (una sola vez)
# Si quieres ser más explícito, puedes comentar esto y llamar init_storage()
# desde app.py o desde la primera página que use datos.
init_storage()
