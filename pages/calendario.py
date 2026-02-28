import datetime
import pandas as pd
import streamlit as st

from services.database import init_db, upsert_calendar_slots, read_table
from services.guesty_api import get_guesty_token, GuestyAuthError
from services.guesty_client import GuestyClient, GuestyAPIError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_calendar_df(raw: pd.DataFrame, listing_id: str) -> pd.DataFrame:
    """
    Normaliza el DataFrame del endpoint de calendario al schema de la DB.
    Campos esperados de la API: date, status, price, minNights, allotment
    """
    col_map = {
        "date":       "date",
        "status":     "status",
        "price":      "price",
        "minNights":  "min_nights",
        "allotment":  "allotment",
    }
    df = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})
    df["listing_id"] = listing_id

    # Asegurar que existen todas las columnas necesarias
    for col in ["date", "status", "price", "min_nights", "allotment"]:
        if col not in df.columns:
            df[col] = None

    return df[["listing_id", "date", "status", "price", "min_nights", "allotment"]].copy()


@st.cache_data(ttl=1800)
def _fetch_calendar(listing_id: str, start: str, end: str) -> pd.DataFrame:
    """Obtiene el calendario desde Guesty, guarda en DB y retorna el DataFrame."""
    token = get_guesty_token()
    client = GuestyClient(token)
    raw = client.get_calendar(listing_id, start, end)
    if raw.empty:
        return pd.DataFrame()
    cal_df = _build_calendar_df(raw, listing_id)
    upsert_calendar_slots(cal_df)
    return cal_df


def _load_listings_for_selector() -> pd.DataFrame:
    """Carga listings de la DB para el selector. Si está vacía retorna DF vacío."""
    return read_table("listings", where="active = true OR active = 1")


# ── Status helpers ────────────────────────────────────────────────────────────

STATUS_LABELS = {
    "available": "Disponible",
    "unavailable": "No disponible",
    "blocked": "Bloqueado",
    "reserved": "Reservado",
    "booked": "Reservado",
}

STATUS_COLORS = {
    "available":   "🟢",
    "unavailable": "🔴",
    "blocked":     "🟠",
    "reserved":    "🔵",
    "booked":      "🔵",
}


def _label(status: str) -> str:
    s = str(status).lower() if status else ""
    icon = STATUS_COLORS.get(s, "⚪")
    label = STATUS_LABELS.get(s, str(status) if status else "—")
    return f"{icon} {label}"


# ── Página principal ──────────────────────────────────────────────────────────

def run():
    st.title("Calendario de Disponibilidad")
    st.caption("Disponibilidad y precios por propiedad. Datos sincronizados con Guesty cada 30 min.")

    init_db()

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### Configuración")

        # Selector de propiedad
        listings_df = _load_listings_for_selector()

        if listings_df.empty:
            st.warning("No hay propiedades en la DB. Ve a la página **Propiedades** primero.")
            listing_id  = None
            listing_nick = None
        else:
            options = listings_df[["id", "nickname"]].dropna().values.tolist()
            labels  = [f"{nick}" for _, nick in options]
            ids     = [lid for lid, _ in options]

            idx = st.selectbox("Propiedad", range(len(labels)),
                               format_func=lambda i: labels[i])
            listing_id   = ids[idx]
            listing_nick = labels[idx]

        st.divider()

        # Rango de fechas
        st.markdown("### Rango de fechas")
        today = datetime.date.today()
        start_date = st.date_input("Desde", value=today,
                                   min_value=today - datetime.timedelta(days=30))
        end_date   = st.date_input("Hasta",
                                   value=today + datetime.timedelta(days=90),
                                   min_value=start_date + datetime.timedelta(days=1))

        st.caption(f"Período: {(end_date - start_date).days} días")

    if listing_id is None:
        st.info("Selecciona una propiedad en el menú lateral.")
        st.stop()

    # ── Cargar calendario ─────────────────────────────────────────────────────
    with st.spinner(f"Cargando calendario de {listing_nick}..."):
        try:
            cal_df = _fetch_calendar(
                listing_id,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            )
        except GuestyAuthError as e:
            st.error(f"Error de autenticación: {e}")
            st.stop()
        except GuestyAPIError as e:
            st.error(f"Error al obtener calendario de Guesty: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Error inesperado: {e}")
            st.stop()

    if cal_df.empty:
        st.warning("No hay datos de calendario para esta propiedad en el rango seleccionado.")
        st.stop()

    # Normalizar fechas
    cal_df["date"] = pd.to_datetime(cal_df["date"]).dt.date

    # Filtrar por rango seleccionado
    cal_df = cal_df[
        (cal_df["date"] >= start_date) &
        (cal_df["date"] <= end_date)
    ].copy()

    # ── Métricas ──────────────────────────────────────────────────────────────
    total_days = len(cal_df)
    available  = (cal_df["status"].str.lower() == "available").sum() if "status" in cal_df.columns else 0
    blocked    = total_days - available
    pct_occ    = (blocked / total_days * 100) if total_days > 0 else 0

    st.markdown(f"### {listing_nick}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total días", total_days)
    c2.metric("Disponibles", int(available))
    c3.metric("No disponibles", int(blocked))
    c4.metric("% Ocupación", f"{pct_occ:.1f}%")

    st.divider()

    # ── Tabla de calendario ───────────────────────────────────────────────────
    display_df = cal_df.copy()
    display_df["Estado"] = display_df["status"].apply(_label)

    col_map = {
        "date":       "Fecha",
        "Estado":     "Estado",
        "price":      "Precio/noche",
        "min_nights": "Noches mínimas",
    }
    disp_cols = [c for c in col_map if c in display_df.columns]
    display_df = display_df[disp_cols].rename(columns=col_map)

    if "Precio/noche" in display_df.columns:
        display_df["Precio/noche"] = display_df["Precio/noche"].apply(
            lambda x: f"${x:,.0f}" if pd.notna(x) and x else "—"
        )

    st.dataframe(
        display_df,
        use_container_width=True,
        height=500,
        hide_index=True,
    )

    # ── Análisis tabs ─────────────────────────────────────────────────────────
    st.divider()
    tab1, tab2 = st.tabs(["Distribución de estados", "Precios"])

    with tab1:
        if "status" in cal_df.columns:
            status_counts = cal_df["status"].value_counts()
            status_display = status_counts.rename(
                index=lambda s: STATUS_LABELS.get(str(s).lower(), s)
            ).reset_index()
            status_display.columns = ["Estado", "Días"]
            st.bar_chart(status_display.set_index("Estado"))

    with tab2:
        price_col = "price"
        if price_col in cal_df.columns:
            price_data = cal_df[cal_df["status"].str.lower() == "available"][[
                "date", price_col
            ]].dropna(subset=[price_col])

            if not price_data.empty:
                price_data = price_data.set_index("date")
                st.line_chart(price_data[price_col])

                avg_price = price_data[price_col].mean()
                min_price = price_data[price_col].min()
                max_price = price_data[price_col].max()

                p1, p2, p3 = st.columns(3)
                p1.metric("Precio promedio", f"${avg_price:,.0f}")
                p2.metric("Precio mínimo",   f"${min_price:,.0f}")
                p3.metric("Precio máximo",   f"${max_price:,.0f}")
            else:
                st.info("No hay datos de precio para días disponibles en este rango.")
        else:
            st.info("Esta propiedad no tiene datos de precio en el calendario.")

    # ── Descarga ──────────────────────────────────────────────────────────────
    st.divider()
    csv = cal_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Descargar calendario CSV",
        data=csv,
        file_name=f"calendario_{listing_nick}_{start_date}_{end_date}.csv",
        mime="text/csv",
        use_container_width=True,
    )
