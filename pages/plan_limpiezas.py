import datetime
import pandas as pd
import streamlit as st
import io
from process_functions import cleanings as fc
from services import guesty_view_endpoint
from services.client_config import get_active_config


# --- Helper Functions ---
def filter_listings(series, excluded_keywords):
    """
    Filtra una Serie de Pandas excluyendo elementos que contengan palabras clave.
    """
    if series is None or len(series) == 0:
        return series

    df = pd.Series(series)
    mask = ~df.astype(str).str.lower().str.contains('|'.join(excluded_keywords), case=False, na=False)
    return df[mask]


def apply_filters_to_reservations(reservations_df, excluded_keywords):
    """
    Aplica filtros de exclusión a las reservas.
    """
    filtered_df = reservations_df.copy()

    for idx, row in filtered_df.iterrows():
        filtered_ci = filter_listings(row['listings_ci'], excluded_keywords)
        filtered_co = filter_listings(row['listings_co'], excluded_keywords)
        filtered_prio = filter_listings(row['listings'], excluded_keywords)

        filtered_df.at[idx, 'listings_ci'] = filtered_ci
        filtered_df.at[idx, 'listings_co'] = filtered_co
        filtered_df.at[idx, 'listings'] = filtered_prio

        filtered_df.at[idx, 'checkIn'] = len(filtered_ci)
        filtered_df.at[idx, 'checkOut'] = len(filtered_co)
        filtered_df.at[idx, 'coincidencias'] = len(filtered_prio)

    return filtered_df


def run():
    config = get_active_config()
    gc = config.guesty
    lc = config.limpiezas

    # --- Configuration from client config ---
    EXCLUDED_KEYWORDS = lc.excluded_keywords
    CLEANING_TIME_MINUTES = lc.cleaning_time_minutes
    PRIORITY_WINDOW_START = lc.priority_window_start
    PRIORITY_WINDOW_END = lc.priority_window_end
    PRIORITY_WINDOW_HOURS = lc.priority_window_hours
    REGULAR_WORK_HOURS = lc.regular_work_hours

    st.header(f"Cronograma de Limpiezas - {config.location_title}")
    st.subheader("Prioridad de Turnovers (Check-in + Check-out el mismo dia)")

    def calculate_staff_needed(priority_cleanings, regular_cleanings):
        """
        Calcula el personal necesario para un dia dado.
        """
        cleaning_time_hours = CLEANING_TIME_MINUTES / 60

        cleanings_per_person_priority = PRIORITY_WINDOW_HOURS / cleaning_time_hours
        staff_priority = int(priority_cleanings / cleanings_per_person_priority) + (
            1 if priority_cleanings % cleanings_per_person_priority > 0 else 0)

        cleanings_per_person_regular = REGULAR_WORK_HOURS / cleaning_time_hours
        staff_regular = int(regular_cleanings / cleanings_per_person_regular) + (
            1 if regular_cleanings % cleanings_per_person_regular > 0 else 0)

        remaining_hours_priority_staff = REGULAR_WORK_HOURS - PRIORITY_WINDOW_HOURS
        additional_cleanings_priority_staff = staff_priority * (remaining_hours_priority_staff / cleaning_time_hours)

        remaining_regular = max(0, regular_cleanings - additional_cleanings_priority_staff)

        staff_additional = int(remaining_regular / cleanings_per_person_regular) + (
            1 if remaining_regular % cleanings_per_person_regular > 0 else 0)

        staff_total = staff_priority + staff_additional

        return staff_priority, staff_additional, staff_total

    # --- Data Source Selector ---
    data_source = st.radio(
        "Fuente de datos",
        ["API (Guesty)", "CSV Upload"],
        horizontal=True,
        help="Usa la API para datos en tiempo real, o sube CSVs para analisis particular"
    )

    # --- Data Loading (Cached) ---
    @st.cache_data(ttl=3600)
    def load_data(_client_id, _view_ci, _view_co, _ci_env, _cs_env, _tz):
        columns = ["checkInDate", "checkOutDate", "listing._id", "listing.nickname",
                    "guestsCount", "confirmationCode"]

        try:
            c_in, c_out = guesty_view_endpoint.load_checkin_checkout(
                _client_id, _ci_env, _cs_env, _view_ci, _view_co, _tz
            )
            data = fc.run_frecuency(
                c_in, c_out,
                columns, "checkInDate", "checkOutDate"
            )
            return data
        except Exception as e:
            st.error(f"Error cargando datos: {str(e)}")
            return None

    def load_csv_data(file_ci, file_co):
        """Process two uploaded CSV files (check-in and check-out)."""
        try:
            df_ci = pd.read_csv(file_ci)
            df_co = pd.read_csv(file_co)
            columns = df_ci.columns.tolist()
            data = fc.run_frecuency(
                df_ci, df_co,
                columns, "CHECK-IN DATE", "CHECK-OUT DATE"
            )
            return data
        except Exception as e:
            st.error(f"Error procesando CSV: {str(e)}")
            return None

    # --- Load and Filter Data ---
    if data_source == "API (Guesty)":
        with st.spinner("Cargando datos desde Guesty..."):
            reservations_raw = load_data(
                config.client_id,
                gc.view_id_checkin,
                gc.view_id_checkout,
                gc.client_id_env_var,
                gc.client_secret_env_var,
                gc.timezone,
            )
    else:
        col_up1, col_up2 = st.columns(2)
        with col_up1:
            csv_ci = st.file_uploader("CSV Check-Ins", type=["csv"], key="csv_ci")
        with col_up2:
            csv_co = st.file_uploader("CSV Check-Outs", type=["csv"], key="csv_co")
        if csv_ci is not None and csv_co is not None:
            reservations_raw = load_csv_data(csv_ci, csv_co)
        else:
            st.info("Sube ambos archivos CSV (Check-Ins y Check-Outs) para comenzar el analisis.")
            st.stop()

    if reservations_raw is None or reservations_raw.empty:
        st.error("No se pudieron cargar los datos. Verifica la conexion o los archivos fuente.")
        st.stop()

    # --- Sidebar / Global Filters ---
    with st.sidebar:
        st.markdown("### Configuracion")

        filter_enabled = st.toggle(
            "Activar filtros de exclusion",
            value=True,
            help="Excluye automaticamente listings que contengan palabras clave especificas"
        )

        if filter_enabled:
            excluded_text = '\n- '.join(EXCLUDED_KEYWORDS)
            st.info(f"**Filtros activos:**\n\nExcluyendo listings que contengan:\n- {excluded_text}")
        else:
            st.warning("Filtros desactivados - Mostrando todos los listings")

    # Aplicar filtros solo si estan activados
    if filter_enabled:
        reservations = apply_filters_to_reservations(reservations_raw, EXCLUDED_KEYWORDS)

        with st.sidebar:
            total_excluded_ci = reservations_raw['checkIn'].sum() - reservations['checkIn'].sum()
            total_excluded_co = reservations_raw['checkOut'].sum() - reservations['checkOut'].sum()
            total_excluded = total_excluded_ci + total_excluded_co

            if total_excluded > 0:
                st.metric("Limpiezas excluidas", total_excluded,
                          delta=f"-{total_excluded_ci} CI, -{total_excluded_co} CO",
                          delta_color="off")
    else:
        reservations = reservations_raw.copy()

    # Selector de fecha
    with st.sidebar:
        st.divider()
        st.markdown("### Seleccionar Fecha")

        min_date = reservations_raw['Date'].min()
        max_date = reservations_raw['Date'].max()

        default_date = datetime.date.today()
        if default_date < min_date:
            default_date = min_date
        elif default_date > max_date:
            default_date = max_date

        selected_date = st.date_input(
            'Fecha a consultar:',
            value=default_date,
            min_value=min_date,
            max_value=max_date
        )

        st.caption(f"Rango disponible: {min_date} a {max_date}")

    # --- Metrics & Details ---
    day_data = reservations[reservations["Date"] == selected_date]
    if not day_data.empty:
        row = day_data.iloc[0]
        ci_list = list(row['listings_ci']) if isinstance(row['listings_ci'], (pd.Series, set)) else row['listings_ci']
        co_list = list(row['listings_co']) if isinstance(row['listings_co'], (pd.Series, set)) else row['listings_co']
        prio_list = list(row['listings']) if isinstance(row['listings'], (pd.Series, set)) else row['listings']

        st.markdown(f"### Resumen del {selected_date.strftime('%A, %d de %B de %Y')}")

        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            st.metric("Check-Ins", len(ci_list))
        with col_m2:
            st.metric("Check-Outs", len(co_list))
        with col_m3:
            st.metric("Prioridad", len(prio_list), help="Propiedades con check-in y check-out el mismo dia")
        with col_m4:
            total_limpiezas = len(co_list)
            st.metric("Total Limpiezas", total_limpiezas)

        with st.expander("Ver detalles del dia seleccionado", expanded=True):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("#### Check-Ins")
                if len(ci_list) > 0:
                    clean_ci_df = pd.DataFrame(list(ci_list), columns=["Propiedad"]).reset_index(drop=True)
                    clean_ci_df.index = clean_ci_df.index + 1
                    st.dataframe(clean_ci_df, use_container_width=True)
                else:
                    st.info("No hay check-ins programados")

            with col2:
                st.markdown("#### Check-Outs")
                if len(co_list) > 0:
                    clean_co_df = pd.DataFrame(list(co_list), columns=["Propiedad"]).reset_index(drop=True)
                    clean_co_df.index = clean_co_df.index + 1
                    st.dataframe(clean_co_df, use_container_width=True)
                else:
                    st.info("No hay check-outs programados")

            with col3:
                st.markdown("#### Turnovers Criticos")
                if len(prio_list) > 0:
                    clean_prio_df = pd.DataFrame(list(prio_list), columns=["Propiedad"]).reset_index(drop=True)
                    clean_prio_df.index = clean_prio_df.index + 1
                    st.dataframe(clean_prio_df, use_container_width=True)
                    st.warning(f"{len(prio_list)} propiedades requieren limpieza urgente")
                else:
                    st.success("No hay turnovers criticos")

        # --- Excel Export Logic ---
        if len(ci_list) > 0 or len(co_list) > 0 or len(prio_list) > 0:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                if len(ci_list) > 0:
                    pd.DataFrame(list(ci_list), columns=["Propiedad"]).to_excel(
                        writer, index=False, sheet_name="Checkins"
                    )
                if len(co_list) > 0:
                    pd.DataFrame(list(co_list), columns=["Propiedad"]).to_excel(
                        writer, index=False, sheet_name="Checkouts"
                    )
                if len(prio_list) > 0:
                    pd.DataFrame(list(prio_list), columns=["Propiedad"]).to_excel(
                        writer, index=False, sheet_name="Prioridad"
                    )

                resumen_df = pd.DataFrame({
                    'Fecha': [selected_date],
                    'Dia': [selected_date.strftime('%A')],
                    'Check-Ins': [len(ci_list)],
                    'Check-Outs': [len(co_list)],
                    'Prioridad': [len(prio_list)],
                    'Total Limpiezas': [total_limpiezas]
                })
                resumen_df.to_excel(writer, index=False, sheet_name="Resumen")

            st.download_button(
                label="Descargar Reporte Excel del Dia",
                data=buffer.getvalue(),
                file_name=f"limpiezas_{selected_date}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    else:
        st.warning(f"No hay reservas registradas para el {selected_date}")
        st.info("Intenta seleccionar otra fecha desde el menu lateral")

    # --- Analysis Tabs ---
    st.divider()
    st.markdown("### Analisis General")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Grafico General",
        "Tabla Maestra",
        "Frec. Coincidencias",
        "Frec. Checkouts",
        "Comparativa Filtros"
    ])

    with tab1:
        st.markdown("#### Comparativa de Check-Ins vs Check-Outs")

        chart_data = reservations[['Date', 'checkIn', 'checkOut']].copy()
        chart_data = chart_data.set_index('Date')

        st.line_chart(chart_data, color=["#2ca02c", "#d62728"])

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("Promedio Check-Ins/dia", f"{reservations['checkIn'].mean():.1f}")
        with col_b:
            st.metric("Promedio Check-Outs/dia", f"{reservations['checkOut'].mean():.1f}")
        with col_c:
            st.metric("Promedio Coincidencias/dia", f"{reservations['coincidencias'].mean():.1f}")

    with tab2:
        st.markdown("#### Tabla Completa de Reservas")

        display_df = reservations[["Date", "week_day", "checkIn", "checkOut", "coincidencias"]].copy()
        display_df.columns = ["Fecha", "Dia", "Check-Ins", "Check-Outs", "Prioridad"]

        st.dataframe(
            display_df,
            use_container_width=True,
            height=400,
            hide_index=True
        )

        csv = display_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Descargar Tabla Completa (CSV)",
            data=csv,
            file_name=f"cronograma_completo_{datetime.date.today()}.csv",
            mime="text/csv",
        )

    with tab3:
        st.markdown("#### Frecuencia de Coincidencias")
        st.caption("Cuantos dias tuvieron 'X' cantidad de coincidencias?")

        frec_coin = reservations['coincidencias'].value_counts().sort_index()

        if not frec_coin.empty:
            st.bar_chart(frec_coin)

            freq_table = frec_coin.reset_index()
            freq_table.columns = ["Cantidad de Coincidencias", "Numero de Dias"]
            st.dataframe(freq_table, use_container_width=True, hide_index=True)

            max_coincidences = frec_coin.idxmax()
            max_days = frec_coin.max()
            st.info(f"**Insight:** {max_days} dias tuvieron {max_coincidences} coincidencia(s)")
        else:
            st.warning("No hay datos de coincidencias disponibles")

    with tab4:
        st.markdown("#### Distribucion de Volumen de Check-Outs")
        st.caption("Frecuencia de dias segun cantidad de check-outs")

        frec_couts = reservations['checkOut'].value_counts().sort_index()

        if not frec_couts.empty:
            st.bar_chart(frec_couts)

            freq_table = frec_couts.reset_index()
            freq_table.columns = ["Cantidad de Check-Outs", "Numero de Dias"]
            st.dataframe(freq_table, use_container_width=True, hide_index=True)

            avg_checkouts = reservations['checkOut'].mean()
            max_checkouts = reservations['checkOut'].max()
            st.info(f"**Insights:** Promedio de {avg_checkouts:.1f} check-outs/dia | Maximo: {max_checkouts}")
        else:
            st.warning("No hay datos de check-outs disponibles")

    with tab5:
        st.markdown("#### Comparativa: Con Filtros vs Sin Filtros")
        st.caption("Visualiza el impacto de los filtros de exclusion en tus datos")

        comparison_data = pd.DataFrame({
            'Date': reservations_raw['Date'],
            'Check-Ins (Sin filtro)': reservations_raw['checkIn'],
            'Check-Outs (Sin filtro)': reservations_raw['checkOut'],
            'Check-Ins (Con filtro)': reservations['checkIn'],
            'Check-Outs (Con filtro)': reservations['checkOut']
        })

        col_g1, col_g2 = st.columns(2)

        with col_g1:
            st.markdown("##### Check-Ins: Comparativa")
            chart_ci = comparison_data[['Date', 'Check-Ins (Sin filtro)', 'Check-Ins (Con filtro)']].set_index('Date')
            st.line_chart(chart_ci, color=["#FF6B6B", "#4ECDC4"])

        with col_g2:
            st.markdown("##### Check-Outs: Comparativa")
            chart_co = comparison_data[['Date', 'Check-Outs (Sin filtro)', 'Check-Outs (Con filtro)']].set_index('Date')
            st.line_chart(chart_co, color=["#FFE66D", "#95E1D3"])

        st.markdown("---")
        st.markdown("##### Resumen Estadistico")

        col_s1, col_s2, col_s3 = st.columns(3)

        with col_s1:
            st.markdown("**Check-Ins**")
            total_ci_raw = reservations_raw['checkIn'].sum()
            total_ci_filtered = reservations['checkIn'].sum()
            diff_ci = total_ci_raw - total_ci_filtered

            st.metric("Total sin filtro", f"{total_ci_raw:,}")
            st.metric("Total con filtro", f"{total_ci_filtered:,}",
                      delta=f"-{diff_ci:,}", delta_color="inverse")
            if total_ci_raw > 0:
                percentage_ci = (diff_ci / total_ci_raw) * 100
                st.metric("% Excluido", f"{percentage_ci:.1f}%")

        with col_s2:
            st.markdown("**Check-Outs**")
            total_co_raw = reservations_raw['checkOut'].sum()
            total_co_filtered = reservations['checkOut'].sum()
            diff_co = total_co_raw - total_co_filtered

            st.metric("Total sin filtro", f"{total_co_raw:,}")
            st.metric("Total con filtro", f"{total_co_filtered:,}",
                      delta=f"-{diff_co:,}", delta_color="inverse")
            if total_co_raw > 0:
                percentage_co = (diff_co / total_co_raw) * 100
                st.metric("% Excluido", f"{percentage_co:.1f}%")

        with col_s3:
            st.markdown("**Coincidencias (Prioridad)**")
            total_prio_raw = reservations_raw['coincidencias'].sum()
            total_prio_filtered = reservations['coincidencias'].sum()
            diff_prio = total_prio_raw - total_prio_filtered

            st.metric("Total sin filtro", f"{total_prio_raw:,}")
            st.metric("Total con filtro", f"{total_prio_filtered:,}",
                      delta=f"-{diff_prio:,}", delta_color="inverse")
            if total_prio_raw > 0:
                percentage_prio = (diff_prio / total_prio_raw) * 100
                st.metric("% Excluido", f"{percentage_prio:.1f}%")

        st.markdown("---")
        st.markdown("##### Tabla Comparativa Detallada")

        comparison_table = pd.DataFrame({
            'Fecha': comparison_data['Date'],
            'CI Sin Filtro': comparison_data['Check-Ins (Sin filtro)'],
            'CI Con Filtro': comparison_data['Check-Ins (Con filtro)'],
            'CI Excluidos': comparison_data['Check-Ins (Sin filtro)'] - comparison_data['Check-Ins (Con filtro)'],
            'CO Sin Filtro': comparison_data['Check-Outs (Sin filtro)'],
            'CO Con Filtro': comparison_data['Check-Outs (Con filtro)'],
            'CO Excluidos': comparison_data['Check-Outs (Sin filtro)'] - comparison_data['Check-Outs (Con filtro)']
        })

        st.dataframe(comparison_table, use_container_width=True, hide_index=True, height=400)

        csv_comparison = comparison_table.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Descargar Comparativa (CSV)",
            data=csv_comparison,
            file_name=f"comparativa_filtros_{datetime.date.today()}.csv",
            mime="text/csv",
            use_container_width=True
        )

        if filter_enabled:
            total_excluded_all = diff_ci + diff_co
            st.success(
                f"Los filtros estan excluyendo **{total_excluded_all:,} limpiezas** en total ({diff_ci:,} check-ins + {diff_co:,} check-outs)")
        else:
            st.info("Los filtros estan desactivados. Activalos desde la barra lateral para ver el impacto.")

    # --- Footer ---
    st.divider()
    st.caption(f"Ultima actualizacion: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if EXCLUDED_KEYWORDS:
        excluded_str = "' u '".join(EXCLUDED_KEYWORDS)
        st.caption(f"Los listings que contengan '{excluded_str}' estan excluidos automaticamente")
