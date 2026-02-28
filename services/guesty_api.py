import streamlit as st
import requests
import time
import os
import json
from pathlib import Path

from services.storage import get_client_data_dir

# Guesty API constants
GUESTY_API_BASE = "https://open-api.guesty.com"

# Buffer before expiry to refresh proactively (1 hour = 3600 seconds)
EXPIRY_BUFFER_SECONDS = 3600


def _get_token_file_path(client_id: str) -> Path:
    """Devuelve la ruta del archivo de token para un cliente."""
    return get_client_data_dir(client_id) / "guesty_token.json"


def _load_token_from_file(token_file_path: Path):
    """Load token and expiry from persistent JSON file"""
    if token_file_path.exists():
        try:
            with open(token_file_path, "r") as f:
                data = json.load(f)
                return data.get("access_token"), float(data.get("expiry_time", 0))
        except (json.JSONDecodeError, IOError):
            st.warning("Invalid or corrupted token file — will request new one.")
            return None, 0
    return None, 0


def _save_token_to_file(token_file_path: Path, token: str, expiry_time: float):
    """Save token and expiry to persistent JSON file"""
    try:
        token_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_file_path, "w") as f:
            json.dump({
                "access_token": token,
                "expiry_time": expiry_time,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            }, f, indent=2)
        st.info("Guesty token saved persistently (valid ~24h).")
    except IOError as e:
        st.error(f"Failed to save token file: {e}")


def get_guesty_token(
    client_id: str,
    client_id_env_var: str,
    client_secret_env_var: str,
) -> str | None:
    """
    Get a valid Guesty access token for the specified client.
    - Reuses from file/session if still valid (with buffer).
    - Requests new one only when necessary (respects 5/day limit).
    Returns the Bearer token string or None on failure.
    """
    token_file_path = _get_token_file_path(client_id)
    token_file_path.parent.mkdir(parents=True, exist_ok=True)

    session_key_token = f"guesty_token_{client_id}"
    session_key_expiry = f"guesty_token_expiry_{client_id}"

    current_time = time.time()

    # 1. Check in-memory session state (fast for current app run)
    if session_key_token in st.session_state and session_key_expiry in st.session_state:
        if current_time < st.session_state[session_key_expiry] - EXPIRY_BUFFER_SECONDS:
            return st.session_state[session_key_token]

    # 2. Check persistent file (survives refreshes, redeploys)
    token, expiry_time = _load_token_from_file(token_file_path)
    if token and current_time < expiry_time - EXPIRY_BUFFER_SECONDS:
        # Sync to session state for this run
        st.session_state[session_key_token] = token
        st.session_state[session_key_expiry] = expiry_time
        return token

    # 3. Token missing, expired, or near expiry → request new one
    cid = os.environ.get(client_id_env_var)
    csecret = os.environ.get(client_secret_env_var)

    if not cid or not csecret:
        st.error(
            f"Guesty API credentials not found. "
            f"Expected env vars: {client_id_env_var}, {client_secret_env_var}"
        )
        return None

    token_url = f"{GUESTY_API_BASE}/oauth2/token"
    payload = {
        'grant_type': 'client_credentials',
        'client_id': cid,
        'client_secret': csecret,
        'scope': 'open-api'
    }

    try:
        with st.spinner("Connecting to Guesty API..."):
            response = requests.post(token_url, data=payload, timeout=15)
            response.raise_for_status()
            data = response.json()

        new_token = data['access_token']
        expires_in = data.get('expires_in', 86400)  # Default to 24h if missing
        new_expiry = current_time + expires_in

        # Save persistently
        _save_token_to_file(token_file_path, new_token, new_expiry)

        # Update session state
        st.session_state[session_key_token] = new_token
        st.session_state[session_key_expiry] = new_expiry

        expiry_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(new_expiry))
        st.success(f"New Guesty token obtained — valid until {expiry_str}")

        return new_token

    except requests.exceptions.HTTPError as e:
        st.error(f"Guesty token request failed (HTTP {e.response.status_code}): {e.response.text}")
    except requests.exceptions.RequestException as e:
        st.error(f"Network error getting Guesty token: {str(e)}")
    except Exception as e:
        st.error(f"Unexpected error: {str(e)}")

    return None
