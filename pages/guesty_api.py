import streamlit as st
import requests
import time
import os
import json
from pathlib import Path

# Guesty API constants
GUESTY_API_BASE = "https://open-api.guesty.com"
TOKEN_FILE_PATH = Path("/app/data/guesty_token.json")  # Persistent on Railway volume

# Buffer before expiry to refresh proactively (1 hour = 3600 seconds)
EXPIRY_BUFFER_SECONDS = 3600


def ensure_data_directory():
    """Create the directory if it doesn't exist (Railway volume)"""
    TOKEN_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_token_from_file():
    """Load token and expiry from persistent JSON file"""
    if TOKEN_FILE_PATH.exists():
        try:
            with open(TOKEN_FILE_PATH, "r") as f:
                data = json.load(f)
                return data.get("access_token"), float(data.get("expiry_time", 0))
        except (json.JSONDecodeError, IOError):
            st.warning("Invalid or corrupted token file — will request new one.")
            return None, 0
    return None, 0


def save_token_to_file(token: str, expiry_time: float):
    """Save token and expiry to persistent JSON file"""
    try:
        with open(TOKEN_FILE_PATH, "w") as f:
            json.dump({
                "access_token": token,
                "expiry_time": expiry_time,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            }, f, indent=2)
        st.info("Guesty token saved persistently (valid ~24h).")
    except IOError as e:
        st.error(f"Failed to save token file: {e}")


@st.cache_resource  # Optional: helps if you have multiple components calling it
def get_guesty_token() -> str | None:
    """
    Get a valid Guesty access token.
    - Reuses from file/session if still valid (with buffer).
    - Requests new one only when necessary (respects 5/day limit).
    Returns the Bearer token string or None on failure.
    """
    ensure_data_directory()

    current_time = time.time()

    # 1. Check in-memory session state (fast for current app run)
    if 'guesty_token' in st.session_state and 'guesty_token_expiry' in st.session_state:
        if current_time < st.session_state.guesty_token_expiry - EXPIRY_BUFFER_SECONDS:
            return st.session_state.guesty_token

    # 2. Check persistent file (survives refreshes, redeploys)
    token, expiry_time = load_token_from_file()
    if token and current_time < expiry_time - EXPIRY_BUFFER_SECONDS:
        # Sync to session state for this run
        st.session_state.guesty_token = token
        st.session_state.guesty_token_expiry = expiry_time
        return token

    # 3. Token missing, expired, or near expiry → request new one
    client_id = os.environ.get('GUESTY_CLIENT_ID')
    client_secret = os.environ.get('GUESTY_CLIENT_SECRET')

    if not client_id or not client_secret:
        st.error("Guesty API credentials not found in environment variables.")
        return None

    token_url = f"{GUESTY_API_BASE}/oauth2/token"
    payload = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'open-api'  # Adjust if you need specific scopes
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
        save_token_to_file(new_token, new_expiry)

        # Update session state
        st.session_state.guesty_token = new_token
        st.session_state.guesty_token_expiry = new_expiry

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


# ────────────────────────────────────────────────
# Example usage in your Streamlit app
# ────────────────────────────────────────────────

st.title("Wellcome Monetización App")

# Optional: Show token status
if 'guesty_token_expiry' in st.session_state:
    expiry_dt = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(st.session_state.guesty_token_expiry))
    st.caption(f"Guesty token status: Valid until {expiry_dt}")

if st.button("Test Guesty Connection & Get Token"):
    token = get_guesty_token()
    if token:
        st.success("Connection successful!")
        st.code(f"Access Token (first 30 chars): {token[:30]}...", language="text")

        # Optional: Test a real API call (example: get current user info)
        headers = {"Authorization": f"Bearer {token}"}
        try:
            test_response = requests.get(f"{GUESTY_API_BASE}/v1/users/me", headers=headers, timeout=10)
            test_response.raise_for_status()
            st.subheader("Test API Response ( /v1/users/me )")
            st.json(test_response.json())
        except Exception as e:
            st.warning(f"Test API call failed: {str(e)} — but token is valid.")
    else:
        st.error("Failed to get Guesty token. Check credentials and logs.")

