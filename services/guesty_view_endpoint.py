import pandas as pd
import streamlit as st
import requests
from services import guesty_api



token = guesty_api.get_guesty_token()
@st.cache_data(ttl=3600)
def fetch_guesty_reservations(view_id, headers):
    base_url = f"https://open-api.guesty.com/v1/reservations-reports"
    params = {
        'active': True,
        'limit': 100,
        'skip': 0,
        'timezone': 'America/Bogota'
    }
    all_rows = []
    try:
        response = requests.get(f"{base_url}/{view_id}", headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        total_records =data.get('total',0)
        all_rows.extend(data.get('results',[]))

        if total_records > 100:
            for skip in range(100, total_records, 100):
                params['skip'] = skip
                resp = requests.get(f"{base_url}/{view_id}", headers=headers(), params=params)
                resp.raise_for_status()
                all_rows.extend(resp.json().get('results',[]))

        return pd.DataFrame(all_rows)
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching data from Guesty: {e}")
        return pd.DataFrame()

    return pd.DataFrame(all_rows)
if token:
    st.success("ok")
    headers = {"Authorization": f"Bearer {token}",'accept': 'application/json; charset=utf-8'}
    view_id_in = "67e4662ff62c503d30ac4b65"
    view_id_out = "66e99b9d462a960d2e7ac304"

    c_in = fetch_guesty_reservations(view_id_in,headers)
    c_out = fetch_guesty_reservations(view_id_out,headers)






