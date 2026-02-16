import pandas as pd
import streamlit as st
import requests
from services import guesty_api


@st.cache_data(ttl=3600)
def fetch_guesty_reservations(view_id, token, timezone="America/Bogota"):
    """Fetch all reservations from a Guesty view, handling pagination."""
    base_url = "https://open-api.guesty.com/v1/reservations-reports"
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json; charset=utf-8",
    }
    params = {
        'active': True,
        'limit': 100,
        'skip': 0,
        'timezone': timezone,
    }
    all_rows = []
    try:
        response = requests.get(f"{base_url}/{view_id}", headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        total_records = data.get('total', 0)
        all_rows.extend(data.get('results', []))

        if total_records > 100:
            for skip in range(100, total_records, 100):
                params['skip'] = skip
                resp = requests.get(f"{base_url}/{view_id}", headers=headers, params=params)
                resp.raise_for_status()
                all_rows.extend(resp.json().get('results', []))

        return pd.DataFrame(all_rows)
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching data from Guesty: {e}")
        return pd.DataFrame()


def load_checkin_checkout(
    client_id: str,
    client_id_env_var: str,
    client_secret_env_var: str,
    view_id_checkin: str,
    view_id_checkout: str,
    timezone: str = "America/Bogota",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load check-in and check-out data for a specific client.
    Returns (c_in, c_out) DataFrames.
    """
    token = guesty_api.get_guesty_token(
        client_id, client_id_env_var, client_secret_env_var
    )
    if not token:
        st.error("Could not obtain Guesty token.")
        return pd.DataFrame(), pd.DataFrame()

    c_in = fetch_guesty_reservations(view_id_checkin, token, timezone)
    c_out = fetch_guesty_reservations(view_id_checkout, token, timezone)
    return c_in, c_out
