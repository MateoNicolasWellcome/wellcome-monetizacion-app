import pandas as pd
import streamlit as st

from services.client_config import get_active_config
from services.database import init_db, upsert_listings, read_table
from services.guesty_api import get_guesty_token
from services.guesty_client import GuestyClient, GuestyAPIError


# ── Helpers de normalización ──────────────────────────────────────────────────

def _build_listings_df(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Toma el DataFrame normalizado de la API (pd.json_normalize) y lo convierte
    al schema de la tabla 'listings' de la DB.
    """
    col_map = {
        "_id":              "id",
        "nickname":         "nickname",
        "title":            "title",
        "bedrooms":         "bedrooms",
        "bathrooms":        "bathrooms",
        "roomType":         "room_type",
        "type":             "type",
        "personCapacity":   "person_capacity",
        "address.city":     "city",
        "address.street":   "street",
        "listed":           "listed",
        "active":           "active",
    }

    df = raw.rename(columns=col_map)

    # Thumbnail: primer elemento del array pictures si existe
    if "pictures" in raw.columns:
        def extract_thumb(pics):
            if isinstance(pics, list) and pics:
                return pics[0].get("thumbnail") or pics[0].get("original", "")
            return ""
        df["thumbnail"] = raw["pictures"].apply(extract_thumb)
    else:
        df["thumbnail"] = ""

    keep = ["id", "nickname", "title", "bedrooms", "bathrooms", "room_type",
            "type", "person_capacity", "city", "street", "listed", "active", "thumbnail"]
    existing = [c for c in keep if c in df.columns]
    return df[existing].copy()


@st.cache_data(ttl=3600)
def _fetch_and_store_listings(client_id: str, client_id_env: str,
                               client_secret_env: str) -> pd.DataFrame:
    """Obtiene listings desde Guesty, los guarda en DB y retorna el DataFrame."""
    token = get_guesty_token(client_id, client_id_env, client_secret_env)
    if not token:
        return pd.DataFrame()
    client = GuestyClient(token)
    raw = client.get_listings()
    if raw.empty:
        return pd.DataFrame()
    listings_df = _build_listings_df(raw)
    upsert_listings(listings_df)
    return listings_df


def _load_listings(client_id: str, client_id_env: str,
                    client_secret_env: str) -> pd.DataFrame:
    """
    Carga listings desde la DB si están frescos; si no, refresca desde Guesty.
    """
    db_df = read_table("listings")
    if not db_df.empty and "fetched_at" in db_df.columns:
        oldest = pd.to_datetime(db_df["fetched_at"]).min()
        age_hours = (pd.Timestamp.utcnow().replace(tzinfo=None) -
                     oldest.replace(tzinfo=None)).total_seconds() / 3600
        if age_hours < 1.0:
            return db_df

    return _fetch_and_store_listings(client_id, client_id_env, client_secret_env)


# ── Página principal ──────────────────────────────────────────────────────────

def run():
    st.title("Propiedades")
    st.caption("Listado de todas las propiedades registradas en Guesty")

    init_db()

    config = get_active_config()
    gc = config.guesty

    # Cargar datos
    with st.spinner("Cargando propiedades desde Guesty..."):
        try:
            df = _load_listings(
                config.client_id,
                gc.client_id_env_var,
                gc.client_secret_env_var,
            )
        except GuestyAPIError as e:
            st.error(f"Error de la API de Guesty: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Error inesperado: {e}")
            st.stop()

    if df is None or (hasattr(df, 'empty') and df.empty):
        st.error("No se pudo obtener token de Guesty. Verifica las credenciales.")
        st.stop()

    if df.empty:
        st.warning("No se encontraron propiedades en Guesty.")
        st.stop()

    # ── Sidebar: filtros ──────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### Filtros")

        # Filtro activo/inactivo
        show_active = st.radio(
            "Estado",
            ["Todas", "Activas", "Inactivas"],
            index=0,
        )

        # Filtro listadas/no listadas
        show_listed = st.radio(
            "Publicadas en canal",
            ["Todas", "Publicadas", "No publicadas"],
            index=0,
        )

        # Filtro por tipo de habitación
        if "room_type" in df.columns:
            tipos = ["Todos"] + sorted(df["room_type"].dropna().unique().tolist())
            tipo_sel = st.selectbox("Tipo de habitación", tipos)
        else:
            tipo_sel = "Todos"

    # Aplicar filtros
    filtered = df.copy()

    if show_active == "Activas" and "active" in filtered.columns:
        filtered = filtered[filtered["active"] == True]
    elif show_active == "Inactivas" and "active" in filtered.columns:
        filtered = filtered[filtered["active"] != True]

    if show_listed == "Publicadas" and "listed" in filtered.columns:
        filtered = filtered[filtered["listed"] == True]
    elif show_listed == "No publicadas" and "listed" in filtered.columns:
        filtered = filtered[filtered["listed"] != True]

    if tipo_sel != "Todos" and "room_type" in filtered.columns:
        filtered = filtered[filtered["room_type"] == tipo_sel]

    # ── Métricas ──────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total propiedades", len(df))
    col2.metric(
        "Activas",
        int(df["active"].sum()) if "active" in df.columns else "—"
    )
    col3.metric(
        "Publicadas",
        int(df["listed"].sum()) if "listed" in df.columns else "—"
    )
    col4.metric("Filtradas", len(filtered))

    st.divider()

    # ── Tabla principal ───────────────────────────────────────────────────────
    display_cols_map = {
        "nickname":         "Nombre",
        "room_type":        "Tipo",
        "bedrooms":         "Hab.",
        "bathrooms":        "Baños",
        "person_capacity":  "Cap.",
        "city":             "Ciudad",
        "active":           "Activa",
        "listed":           "Publicada",
    }
    display_cols = [c for c in display_cols_map if c in filtered.columns]
    display_df = filtered[display_cols].rename(columns=display_cols_map).reset_index(drop=True)
    display_df.index = display_df.index + 1

    st.dataframe(
        display_df,
        use_container_width=True,
        height=450,
        column_config={
            "Activa":    st.column_config.CheckboxColumn("Activa"),
            "Publicada": st.column_config.CheckboxColumn("Publicada"),
        },
    )

    # ── Detalle por propiedad ─────────────────────────────────────────────────
    if "nickname" in filtered.columns and len(filtered) > 0:
        st.divider()
        st.markdown("### Detalle de propiedad")

        options = ["— Seleccionar —"] + filtered["nickname"].dropna().tolist()
        selected_nick = st.selectbox("Selecciona una propiedad", options)

        if selected_nick != "— Seleccionar —":
            row = filtered[filtered["nickname"] == selected_nick].iloc[0]

            c1, c2 = st.columns([1, 2])
            with c1:
                if row.get("thumbnail"):
                    st.image(row["thumbnail"], use_column_width=True)
                else:
                    st.info("Sin imagen disponible")
            with c2:
                st.markdown(f"**{row.get('nickname', '—')}**")
                fields = [
                    ("ID Guesty",      "id"),
                    ("Título",         "title"),
                    ("Tipo",           "room_type"),
                    ("Hab. / Baños",   None),
                    ("Capacidad",      "person_capacity"),
                    ("Ciudad",         "city"),
                    ("Dirección",      "street"),
                ]
                for label, key in fields:
                    if key is None:
                        beds  = row.get("bedrooms", "—")
                        baths = row.get("bathrooms", "—")
                        st.write(f"**{label}:** {beds} hab. / {baths} baños")
                    elif key in row:
                        st.write(f"**{label}:** {row[key]}")

    # ── Descarga CSV ──────────────────────────────────────────────────────────
    st.divider()
    csv = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Descargar CSV",
        data=csv,
        file_name="propiedades_guesty.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.caption(f"Datos actualizados automáticamente cada hora desde Guesty.")
