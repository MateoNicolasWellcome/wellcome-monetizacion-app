import datetime
import io

import pandas as pd
import streamlit as st

from services.database import init_db, upsert_reservations, read_table
from services.guesty_api import get_guesty_token, GuestyAuthError
from services.guesty_client import GuestyClient, GuestyAPIError


# ── Helpers de normalización ──────────────────────────────────────────────────

def _build_reservations_df(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza el DataFrame de pd.json_normalize(reservations API)
    al schema de la tabla 'reservations' de la DB.
    """
    col_map = {
        "_id":                   "id",
        "confirmationCode":      "confirmation_code",
        "listing._id":           "listing_id",
        "listing.nickname":      "listing_nickname",
        "checkIn":               "check_in",
        "checkOut":              "check_out",
        "status":                "status",
        "source":                "source",
        "money.currency":        "currency",
        "money.totalPrice":      "total_price",
        "money.fareAccommodation": "fare_accommodation",
        "money.hostServiceFee":  "host_service_fee",
        "money.tax":             "tax",
        "guest.fullName":        "guest_name",
    }

    df = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})

    # Calcular noches
    if "check_in" in df.columns and "check_out" in df.columns:
        ci = pd.to_datetime(df["check_in"], errors="coerce")
        co = pd.to_datetime(df["check_out"], errors="coerce")
        df["nights"] = (co - ci).dt.days
    else:
        df["nights"] = None

    keep = ["id", "confirmation_code", "listing_id", "listing_nickname",
            "check_in", "check_out", "nights", "status", "source", "currency",
            "total_price", "fare_accommodation", "host_service_fee", "tax", "guest_name"]
    existing = [c for c in keep if c in df.columns]
    return df[existing].copy()


@st.cache_data(ttl=3600)
def _fetch_reservations(check_in_from: str, check_in_to: str,
                         statuses_key: str) -> pd.DataFrame:
    """
    Obtiene reservas desde Guesty (con caché por rango de fechas),
    las guarda en DB y retorna el DataFrame normalizado.
    statuses_key es un string para que @st.cache_data pueda hashear la lista.
    """
    token = get_guesty_token()
    client = GuestyClient(token)
    statuses = statuses_key.split(",") if statuses_key else None
    raw = client.get_reservations(
        check_in_from=check_in_from,
        check_in_to=check_in_to,
        statuses=statuses,
    )
    if raw.empty:
        return pd.DataFrame()

    df = _build_reservations_df(raw)
    upsert_reservations(df)
    return df


def _load_reservations(check_in_from: str, check_in_to: str) -> pd.DataFrame:
    """
    Carga reservas: primero intenta la DB (si hay datos del rango),
    si no refresca desde la API.
    """
    # Intentar leer de DB primero para el rango
    db_df = read_table(
        "reservations",
        where="check_in >= :from_date AND check_in <= :to_date",
        params={"from_date": check_in_from, "to_date": check_in_to},
    )

    if not db_df.empty:
        if "fetched_at" in db_df.columns:
            oldest = pd.to_datetime(db_df["fetched_at"]).min()
            age_hours = (pd.Timestamp.utcnow().replace(tzinfo=None) -
                         oldest.replace(tzinfo=None)).total_seconds() / 3600
            if age_hours < 1.0:
                return db_df

    # Stale o vacío → refrescar
    return _fetch_reservations(
        check_in_from, check_in_to,
        "confirmed,checked_out",
    )


# ── Página principal ──────────────────────────────────────────────────────────

def run():
    st.title("Ingresos")
    st.caption("Análisis de revenue basado en reservas de Guesty")

    init_db()

    # ── Sidebar: filtros ──────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### Filtros")

        today = datetime.date.today()
        default_start = today.replace(day=1) - datetime.timedelta(days=180)

        start_date = st.date_input("Check-in desde", value=default_start)
        end_date   = st.date_input("Check-in hasta", value=today)

        if start_date >= end_date:
            st.error("La fecha de inicio debe ser anterior a la de fin.")
            st.stop()

        # Filtro por propiedad (post-carga)
        st.divider()
        st.markdown("### Propiedad")
        st.caption("Se aplica después de cargar los datos")

    # ── Cargar datos ──────────────────────────────────────────────────────────
    with st.spinner("Cargando reservas desde Guesty..."):
        try:
            df = _load_reservations(
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            )
        except GuestyAuthError as e:
            st.error(f"Error de autenticación: {e}")
            st.stop()
        except GuestyAPIError as e:
            st.error(f"Error de la API de Guesty: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Error inesperado: {e}")
            st.stop()

    if df.empty:
        st.warning("No se encontraron reservas para el período seleccionado.")
        st.stop()

    # Normalizar tipos
    df["check_in"]  = pd.to_datetime(df["check_in"],  errors="coerce")
    df["check_out"] = pd.to_datetime(df["check_out"], errors="coerce")
    df["total_price"] = pd.to_numeric(df["total_price"], errors="coerce").fillna(0)
    df["nights"]      = pd.to_numeric(df["nights"],      errors="coerce").fillna(0)

    # Filtro por propiedad en sidebar (una vez que tenemos datos)
    with st.sidebar:
        if "listing_nickname" in df.columns:
            props = ["Todas"] + sorted(df["listing_nickname"].dropna().unique().tolist())
            prop_sel = st.selectbox("Propiedad", props)
        else:
            prop_sel = "Todas"

    if prop_sel != "Todas" and "listing_nickname" in df.columns:
        df = df[df["listing_nickname"] == prop_sel]

    # ── Métricas globales ─────────────────────────────────────────────────────
    total_revenue = df["total_price"].sum()
    total_res     = len(df)
    total_nights  = df["nights"].sum()
    adr           = total_revenue / total_nights if total_nights > 0 else 0

    st.markdown("### Resumen del período")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue total",  f"${total_revenue:,.0f}")
    c2.metric("Reservas",       f"{total_res:,}")
    c3.metric("Noches vendidas",f"{int(total_nights):,}")
    c4.metric("ADR",            f"${adr:,.0f}", help="Average Daily Rate")

    st.divider()

    # ── Tabs de análisis ──────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "Revenue por propiedad",
        "Revenue por mes",
        "Detalle de reservas",
    ])

    with tab1:
        st.markdown("#### Revenue por propiedad")

        if "listing_nickname" in df.columns:
            by_prop = (
                df.groupby("listing_nickname")
                  .agg(
                      revenue=("total_price", "sum"),
                      reservas=("id", "count"),
                      noches=("nights", "sum"),
                  )
                  .sort_values("revenue", ascending=False)
                  .reset_index()
            )
            by_prop["adr"] = (by_prop["revenue"] / by_prop["noches"]
                               .replace(0, float("nan"))).round(0)

            # Bar chart
            st.bar_chart(by_prop.set_index("listing_nickname")["revenue"])

            # Tabla formateada
            by_prop_display = by_prop.copy()
            by_prop_display["revenue"] = by_prop_display["revenue"].apply(
                lambda x: f"${x:,.0f}"
            )
            by_prop_display["adr"] = by_prop_display["adr"].apply(
                lambda x: f"${x:,.0f}" if pd.notna(x) else "—"
            )
            by_prop_display.columns = [
                "Propiedad", "Revenue", "Reservas", "Noches", "ADR"
            ]
            st.dataframe(by_prop_display, use_container_width=True, hide_index=True)
        else:
            st.warning("No hay datos de propiedad en las reservas.")

    with tab2:
        st.markdown("#### Revenue mensual")

        if "check_in" in df.columns:
            df["mes"] = df["check_in"].dt.to_period("M").astype(str)
            by_month = (
                df.groupby("mes")
                  .agg(
                      revenue=("total_price", "sum"),
                      reservas=("id", "count"),
                  )
                  .reset_index()
                  .sort_values("mes")
            )

            st.line_chart(by_month.set_index("mes")["revenue"])

            by_month_display = by_month.copy()
            by_month_display["revenue"] = by_month_display["revenue"].apply(
                lambda x: f"${x:,.0f}"
            )
            by_month_display.columns = ["Mes", "Revenue", "Reservas"]
            st.dataframe(by_month_display, use_container_width=True, hide_index=True)
        else:
            st.warning("No hay datos de fechas en las reservas.")

    with tab3:
        st.markdown("#### Detalle de reservas")

        disp_cols_map = {
            "confirmation_code":  "Código",
            "listing_nickname":   "Propiedad",
            "check_in":           "Check-in",
            "check_out":          "Check-out",
            "nights":             "Noches",
            "status":             "Estado",
            "source":             "Canal",
            "total_price":        "Revenue",
            "guest_name":         "Huésped",
        }
        disp_cols = [c for c in disp_cols_map if c in df.columns]
        detail_df = df[disp_cols].rename(columns=disp_cols_map).copy()

        if "Revenue" in detail_df.columns:
            detail_df["Revenue"] = detail_df["Revenue"].apply(
                lambda x: f"${x:,.0f}"
            )

        st.dataframe(detail_df, use_container_width=True, height=450, hide_index=True)

    # ── Descarga Excel ────────────────────────────────────────────────────────
    st.divider()

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        # Hoja 1: resumen por propiedad
        if "listing_nickname" in df.columns:
            by_prop_raw = (
                df.groupby("listing_nickname")
                  .agg(revenue=("total_price", "sum"),
                       reservas=("id", "count"),
                       noches=("nights", "sum"))
                  .reset_index()
            )
            by_prop_raw.to_excel(writer, index=False, sheet_name="Por propiedad")

        # Hoja 2: detalle reservas
        detail_export = df[disp_cols].rename(columns=disp_cols_map)
        detail_export.to_excel(writer, index=False, sheet_name="Detalle reservas")

    st.download_button(
        label="Descargar Excel",
        data=buffer.getvalue(),
        file_name=f"ingresos_{start_date}_{end_date}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.caption(f"Revenue en la moneda reportada por Guesty (field: money.currency).")
