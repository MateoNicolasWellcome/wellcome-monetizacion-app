import requests
import time
import os
import json
from pathlib import Path

# ── Guesty API constants ─────────────────────────────────────────────────────
GUESTY_API_BASE = "https://open-api.guesty.com"
TOKEN_FILE_PATH = Path("/app/data/guesty_token.json")   # persiste en Railway Volume
EXPIRY_BUFFER_SECONDS = 3600                            # refrescar 1h antes de expirar

# Caché en memoria del proceso (comparte estado en un mismo worker)
_token_cache: dict = {"token": None, "expiry": 0.0}


class GuestyAuthError(Exception):
    """Se lanza cuando no se puede obtener un token válido de Guesty."""
    pass


# ── Helpers de archivo ────────────────────────────────────────────────────────

def _ensure_data_directory() -> None:
    TOKEN_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_token_from_file() -> tuple[str | None, float]:
    """Lee token y expiración del archivo persistente JSON."""
    if TOKEN_FILE_PATH.exists():
        try:
            with open(TOKEN_FILE_PATH, "r") as f:
                data = json.load(f)
            return data.get("access_token"), float(data.get("expiry_time", 0))
        except (json.JSONDecodeError, IOError, ValueError):
            pass
    return None, 0.0


def _save_token_to_file(token: str, expiry_time: float) -> None:
    """Guarda token y expiración en el archivo persistente JSON."""
    try:
        with open(TOKEN_FILE_PATH, "w") as f:
            json.dump(
                {
                    "access_token": token,
                    "expiry_time": expiry_time,
                    "saved_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                },
                f,
                indent=2,
            )
    except IOError:
        pass  # no crítico — el token en memoria sigue siendo válido


# ── API pública ───────────────────────────────────────────────────────────────

def get_guesty_token() -> str:
    """
    Retorna un Bearer token válido para la API de Guesty.

    Estrategia de caché (en orden):
      1. Variable de módulo en memoria (más rápido, dura mientras el proceso corra)
      2. Archivo JSON persistente en /app/data/ (sobrevive reinicios en Railway)
      3. Petición nueva a Guesty OAuth2 (máx. 5/día por su límite)

    Raises:
        GuestyAuthError: si no hay credenciales o la petición falla.
    """
    _ensure_data_directory()
    current_time = time.time()

    # 1. Caché en memoria
    if _token_cache["token"] and current_time < _token_cache["expiry"] - EXPIRY_BUFFER_SECONDS:
        return _token_cache["token"]

    # 2. Archivo persistente
    token, expiry_time = _load_token_from_file()
    if token and current_time < expiry_time - EXPIRY_BUFFER_SECONDS:
        _token_cache["token"] = token
        _token_cache["expiry"] = expiry_time
        return token

    # 3. Solicitar token nuevo
    client_id = os.environ.get("GUESTY_CLIENT_ID")
    client_secret = os.environ.get("GUESTY_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise GuestyAuthError(
            "Credenciales de Guesty no encontradas. "
            "Define GUESTY_CLIENT_ID y GUESTY_CLIENT_SECRET como variables de entorno."
        )

    try:
        response = requests.post(
            f"{GUESTY_API_BASE}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "open-api",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.HTTPError as e:
        raise GuestyAuthError(
            f"Error HTTP al solicitar token de Guesty ({e.response.status_code}): "
            f"{e.response.text}"
        ) from e
    except requests.exceptions.RequestException as e:
        raise GuestyAuthError(f"Error de red al conectar con Guesty: {e}") from e

    new_token: str = data["access_token"]
    expires_in: int = data.get("expires_in", 86400)
    new_expiry = current_time + expires_in

    _save_token_to_file(new_token, new_expiry)
    _token_cache["token"] = new_token
    _token_cache["expiry"] = new_expiry

    return new_token


def token_expiry_info() -> dict:
    """
    Retorna información sobre el estado del token actual.
    Útil para mostrar en la UI sin re-solicitar el token.

    Returns:
        {"token_valid": bool, "expiry_utc": str | None, "source": str}
    """
    current_time = time.time()

    # Revisar memoria
    if _token_cache["token"] and _token_cache["expiry"] > current_time:
        return {
            "token_valid": True,
            "expiry_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(_token_cache["expiry"])),
            "source": "memory",
        }

    # Revisar archivo
    token, expiry_time = _load_token_from_file()
    if token and expiry_time > current_time:
        return {
            "token_valid": True,
            "expiry_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(expiry_time)),
            "source": "file",
        }

    return {"token_valid": False, "expiry_utc": None, "source": "none"}
