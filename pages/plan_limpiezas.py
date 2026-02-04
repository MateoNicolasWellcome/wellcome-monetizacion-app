import datetime
import pandas as pd
import streamlit as st
import io
from process_functions import cleanings as fc
from services import guesty_view_endpoint

# --- Page Config ---

st.header("📅 Cronograma de Limpiezas - Bogotá 2026")
st.subheader("Prioridad de Turnovers (Check-in + Check-out el mismo día)")

# --- Configuration ---
EXCLUDED_KEYWORDS = ["4991", "orange"]  # Palabras clave a excluir

# Configuración de personal
CLEANING_TIME_MINUTES = 40  # Tiempo máximo por limpieza en minutos
PRIORITY_WINDOW_START = 11  # 11:00 AM
PRIORITY_WINDOW_END = 15  # 3:00 PM (15:00)
PRIORITY_WINDOW_HOURS = PRIORITY_WINDOW_END - PRIORITY_WINDOW_START  # 4 horas
REGULAR_WORK_HOURS = 8  # Horas de trabajo regular por día


# --- Helper Functions ---
def filter_listings(series, excluded_keywords):
    """
    Filtra una Serie de Pandas excluyendo elementos que contengan palabras clave.

    Args:
        series: Serie de pandas con los nombres de listings
        excluded_keywords: Lista de palabras clave a excluir

    Returns:
        Serie filtrada
    """
    if series is None or len(series) == 0:
        return series

    # Convertir a DataFrame para facilitar el filtrado
    df = pd.Series(series)

    # Crear máscara para excluir listings que contengan cualquiera de las palabras clave
    mask = ~df.astype(str).str.lower().str.contains('|'.join(excluded_keywords), case=False, na=False)

    return df[mask]


def calculate_staff_needed(priority_cleanings, regular_cleanings):
    """
    Calcula el personal necesario para un día dado.

    Args:
        priority_cleanings: Número de limpiezas prioritarias (ventana 11am-3pm)
        regular_cleanings: Número de limpiezas regulares (día completo)

    Returns:
        tuple: (personal_prioritario, personal_regular, personal_total)
    """
    # Convertir tiempo de limpieza a horas
    cleaning_time_hours = CLEANING_TIME_MINUTES / 60

    # Personal para limpiezas prioritarias (ventana de 4 horas)
    cleanings_per_person_priority = PRIORITY_WINDOW_HOURS / cleaning_time_hours
    staff_priority = int(priority_cleanings / cleanings_per_person_priority) + (
        1 if priority_cleanings % cleanings_per_person_priority > 0 else 0)

    # Personal para limpiezas regulares (8 horas de trabajo)
    cleanings_per_person_regular = REGULAR_WORK_HOURS / cleaning_time_hours
    staff_regular = int(regular_cleanings / cleanings_per_person_regular) + (
        1 if regular_cleanings % cleanings_per_person_regular > 0 else 0)

    # El personal prioritario también puede hacer limpiezas regulares después de las 3pm
    # Calculamos si necesitamos personal adicional
    remaining_hours_priority_staff = REGULAR_WORK_HOURS - PRIORITY_WINDOW_HOURS  # 4 horas restantes
    additional_cleanings_priority_staff = staff_priority * (remaining_hours_priority_staff / cleaning_time_hours)

    # Limpiezas regulares que quedan después de que el personal prioritario ayude
    remaining_regular = max(0, regular_cleanings - additional_cleanings_priority_staff)

    # Personal adicional necesario solo para regulares
    staff_additional = int(remaining_regular / cleanings_per_person_regular) + (
        1 if remaining_regular % cleanings_per_person_regular > 0 else 0)

    # Total de personal necesario
    staff_total = staff_priority + staff_additional

    return staff_priority, staff_additional, staff_total


def apply_filters_to_reservations(reservations_df, excluded_keywords):
    """
    Aplica filtros de exclusión a

    Args:
        reservations_df: DataFrame con las reservas
        excluded_keywords: Lista de palabras clave a excluir

    Returns:
        DataFrame filtrado con contadores actualizados
    """
    filtered_df = reservations_df.copy()

    for idx, row in filtered_df.iterrows():
        # Filtrar cada lista de listings
        filtered_ci = filter_listings(row['listings_ci'], excluded_keywords)
        filtered_co = filter_listings(row['listings_co'], excluded_keywords)
        filtered_prio = filter_listings(row['listings'], excluded_keywords)

        # Actualizar las listas filtradas
        filtered_df.at[idx, 'listings_ci'] = filtered_ci
        filtered_df.at[idx, 'listings_co'] = filtered_co
        filtered_df.at[idx, 'listings'] = filtered_prio

        # Actualizar los contadores
        filtered_df.at[idx, 'checkIn'] = len(filtered_ci)
        filtered_df.at[idx, 'checkOut'] = len(filtered_co)
        filtered_df.at[idx, 'coincidencias'] = len(filtered_prio)

    return filtered_df


# --- Data Loading (Cached) ---
@st.cache_data(ttl=3600)
def load_data():
    columns = ["checkInDate", "checkOutDate", "listing._id", "listing.nickname",
               "guestsCount", "confirmationCode"]

    try:
        data = fc.run_frecuency(
            guesty_view_endpoint.c_in,
            guesty_view_endpoint.c_out,
            columns, "checkInDate", "checkOutDate"
        )
        return data
    except Exception as e:
        st.error(f"❌ Error cargando datos: {str(e)}")
        return None


# --- Load and Filter Data ---
with st.spinner("📊 Cargando datos..."):
    reservations_raw = load_data()

if reservations_raw is None or reservations_raw.empty:
    st.error("No se pudieron cargar los datos. Verifica la conexión o los archivos fuente.")
    st.stop()

# --- Sidebar / Global Filters ---
with st.sidebar:
    st.markdown("### ⚙️ Configuración")

    # Toggle para activar/desactivar filtros
    filter_enabled = st.toggle(
        "🔍 Activar filtros de exclusión",
        value=True,
        help="Excluye automáticamente listings que contengan palabras clave específicas"
    )

    if filter_enabled:
        excluded_text = '\n- '.join(EXCLUDED_KEYWORDS)
        st.info(f"**Filtros activos:**\n\nExcluyendo listings que contengan:\n- {excluded_text}")
    else:
        st.warning("⚠️ Filtros desactivados - Mostrando todos los listings")

# Aplicar filtros solo si están activados
if filter_enabled:
    reservations = apply_filters_to_reservations(reservations_raw, EXCLUDED_KEYWORDS)

    # Estadísticas de filtrado
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

# Selector de fecha (fuera del sidebar, dentro del mismo bloque)
with st.sidebar:
    st.divider()

    # Selector de fecha
    st.markdown("### 📅 Seleccionar Fecha")

    # Obtener rango de fechas disponibles (siempre desde raw data)
    min_date = reservations_raw['Date'].min()
    max_date = reservations_raw['Date'].max()

    # Asegurar que la fecha de hoy esté dentro del rango
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
day_data = reservations[reservations["Date"] == selected_date]
if not day_data.empty:
    row = day_data.iloc[0]
    # ci_list = row['listings_ci']
    # co_list = row['listings_co']
    # prio_list = row['listings']
    ci_list = list(row['listings_ci']) if isinstance(row['listings_ci'], (pd.Series, set)) else row['listings_ci']
    co_list = list(row['listings_co']) if isinstance(row['listings_co'], (pd.Series, set)) else row['listings_co']
    prio_list = list(row['listings']) if isinstance(row['listings'], (pd.Series, set)) else row['listings']



    # Mostrar resumen del día
    st.markdown(f"### 📊 Resumen del {selected_date.strftime('%A, %d de %B de %Y')}")

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric("✅ Check-Ins", len(ci_list))
    with col_m2:
        st.metric("🚪 Check-Outs", len(co_list))
    with col_m3:
        st.metric("⚠️ Prioridad", len(prio_list), help="Propiedades con check-in y check-out el mismo día")
    with col_m4:
        total_limpiezas =   len(co_list)
        st.metric("🧹 Total Limpiezas", total_limpiezas)

    with st.expander("🔍 Ver detalles del día seleccionado", expanded=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("#### ✅ Check-Ins")
            if len(ci_list) > 0:
                clean_ci_df = pd.DataFrame(list(ci_list), columns=["Propiedad"]).reset_index(drop=True)
                clean_ci_df.index = clean_ci_df.index + 1
                st.dataframe(clean_ci_df, use_container_width=True)
            else:
                st.info("No hay check-ins programados")

        with col2:
            st.markdown("#### 🚪 Check-Outs")
            if len(co_list) > 0:
                clean_co_df = pd.DataFrame(list(co_list), columns=["Propiedad"]).reset_index(drop=True)
                clean_co_df.index = clean_co_df.index + 1
                st.dataframe(clean_co_df, use_container_width=True)
            else:
                st.info("No hay check-outs programados")

        with col3:
            st.markdown("#### ⚠️ Turnovers Críticos")
            if len(prio_list) > 0:
                clean_prio_df = pd.DataFrame(list(prio_list), columns=["Propiedad"]).reset_index(drop=True)
                clean_prio_df.index = clean_prio_df.index + 1
                st.dataframe(clean_prio_df, use_container_width=True)
                st.warning(f"⚠️ {len(prio_list)} propiedades requieren limpieza urgente")
            else:
                st.success("✅ No hay turnovers críticos")

    # --- Excel Export Logic ---
    if len(ci_list) > 0 or len(co_list) > 0 or len(prio_list) > 0:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            # Sheet 1: Check-ins
            if len(ci_list) > 0:
                pd.DataFrame(list(ci_list), columns=["Propiedad"]).to_excel(
                    writer, index=False, sheet_name="Checkins"
                )

            # Sheet 2: Check-outs
            if len(co_list) > 0:
                pd.DataFrame(list(co_list), columns=["Propiedad"]).to_excel(
                    writer, index=False, sheet_name="Checkouts"
                )

            # Sheet 3: Prioridad
            if len(prio_list) > 0:
                pd.DataFrame(list(prio_list), columns=["Propiedad"]).to_excel(
                    writer, index=False, sheet_name="Prioridad"
                )

            # Sheet 4: Resumen
            resumen_df = pd.DataFrame({
                'Fecha': [selected_date],
                'Día': [selected_date.strftime('%A')],
                'Check-Ins': [len(ci_list)],
                'Check-Outs': [len(co_list)],
                'Prioridad': [len(prio_list)],
                'Total Limpiezas': [total_limpiezas]
            })
            resumen_df.to_excel(writer, index=False, sheet_name="Resumen")

        st.download_button(
            label="⬇️ Descargar Reporte Excel del Día",
            data=buffer.getvalue(),
            file_name=f"limpiezas_{selected_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
else:
    st.warning(f"⚠️ No hay reservas registradas para el {selected_date}")
    st.info("Intenta seleccionar otra fecha desde el menú lateral")

# --- Analysis Tabs ---
st.divider()
st.markdown("### 📊 Análisis General")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Gráfico General",
    "📋 Tabla Maestra",
    "🔄 Frec. Coincidencias",
    "🚪 Frec. Checkouts",
    "🔬 Comparativa Filtros"
])

with tab1:
    st.markdown("#### Comparativa de Check-Ins vs Check-Outs")

    # Crear gráfico con colores personalizados
    chart_data = reservations[['Date', 'checkIn', 'checkOut']].copy()
    chart_data = chart_data.set_index('Date')

    st.line_chart(chart_data, color=["#2ca02c", "#d62728"])

    # Estadísticas generales
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Promedio Check-Ins/día", f"{reservations['checkIn'].mean():.1f}")
    with col_b:
        st.metric("Promedio Check-Outs/día", f"{reservations['checkOut'].mean():.1f}")
    with col_c:
        st.metric("Promedio Coincidencias/día", f"{reservations['coincidencias'].mean():.1f}")

with tab2:
    st.markdown("#### Tabla Completa de Reservas")

    # Formatear la tabla
    display_df = reservations[["Date", "week_day", "checkIn", "checkOut", "coincidencias"]].copy()
    display_df.columns = ["Fecha", "Día", "Check-Ins", "Check-Outs", "Prioridad"]

    st.dataframe(
        display_df,
        use_container_width=True,
        height=400,
        hide_index=True
    )

    # Botón de descarga de tabla completa
    csv = display_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="⬇️ Descargar Tabla Completa (CSV)",
        data=csv,
        file_name=f"cronograma_completo_{datetime.date.today()}.csv",
        mime="text/csv",
    )

with tab3:
    st.markdown("#### Frecuencia de Coincidencias")
    st.caption("¿Cuántos días tuvieron 'X' cantidad de coincidencias?")

    frec_coin = reservations['coincidencias'].value_counts().sort_index()

    if not frec_coin.empty:
        st.bar_chart(frec_coin)

        # Tabla formateada
        freq_table = frec_coin.reset_index()
        freq_table.columns = ["Cantidad de Coincidencias", "Número de Días"]
        st.dataframe(freq_table, use_container_width=True, hide_index=True)

        # Insight
        max_coincidences = frec_coin.idxmax()
        max_days = frec_coin.max()
        st.info(f"💡 **Insight:** {max_days} días tuvieron {max_coincidences} coincidencia(s)")
    else:
        st.warning("No hay datos de coincidencias disponibles")

with tab4:
    st.markdown("#### Distribución de Volumen de Check-Outs")
    st.caption("Frecuencia de días según cantidad de check-outs")

    frec_couts = reservations['checkOut'].value_counts().sort_index()

    if not frec_couts.empty:
        st.bar_chart(frec_couts)

        # Tabla formateada
        freq_table = frec_couts.reset_index()
        freq_table.columns = ["Cantidad de Check-Outs", "Número de Días"]
        st.dataframe(freq_table, use_container_width=True, hide_index=True)

        # Insights
        avg_checkouts = reservations['checkOut'].mean()
        max_checkouts = reservations['checkOut'].max()
        st.info(f"💡 **Insights:** Promedio de {avg_checkouts:.1f} check-outs/día | Máximo: {max_checkouts}")
    else:
        st.warning("No hay datos de check-outs disponibles")

with tab5:
    st.markdown("#### 🔬 Comparativa: Con Filtros vs Sin Filtros")
    st.caption("Visualiza el impacto de los filtros de exclusión en tus datos")

    # Preparar datos para comparación
    comparison_data = pd.DataFrame({
        'Date': reservations_raw['Date'],
        'Check-Ins (Sin filtro)': reservations_raw['checkIn'],
        'Check-Outs (Sin filtro)': reservations_raw['checkOut'],
        'Check-Ins (Con filtro)': reservations['checkIn'],
        'Check-Outs (Con filtro)': reservations['checkOut']
    })

    # Gráfico comparativo
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.markdown("##### 📊 Check-Ins: Comparativa")
        chart_ci = comparison_data[['Date', 'Check-Ins (Sin filtro)', 'Check-Ins (Con filtro)']].set_index('Date')
        st.line_chart(chart_ci, color=["#FF6B6B", "#4ECDC4"])

    with col_g2:
        st.markdown("##### 📊 Check-Outs: Comparativa")
        chart_co = comparison_data[['Date', 'Check-Outs (Sin filtro)', 'Check-Outs (Con filtro)']].set_index('Date')
        st.line_chart(chart_co, color=["#FFE66D", "#95E1D3"])

    # Estadísticas comparativas
    st.markdown("---")
    st.markdown("##### 📈 Resumen Estadístico")

    col_s1, col_s2, col_s3 = st.columns(3)

    with col_s1:
        st.markdown("**Check-Ins**")
        total_ci_raw = reservations_raw['checkIn'].sum()
        total_ci_filtered = reservations['checkIn'].sum()
        diff_ci = total_ci_raw - total_ci_filtered

        st.metric(
            "Total sin filtro",
            f"{total_ci_raw:,}",
            help="Total de check-ins antes de aplicar filtros"
        )
        st.metric(
            "Total con filtro",
            f"{total_ci_filtered:,}",
            delta=f"-{diff_ci:,}",
            delta_color="inverse",
            help="Total de check-ins después de aplicar filtros"
        )
        if total_ci_raw > 0:
            percentage_ci = (diff_ci / total_ci_raw) * 100
            st.metric(
                "% Excluido",
                f"{percentage_ci:.1f}%"
            )

    with col_s2:
        st.markdown("**Check-Outs**")
        total_co_raw = reservations_raw['checkOut'].sum()
        total_co_filtered = reservations['checkOut'].sum()
        diff_co = total_co_raw - total_co_filtered

        st.metric(
            "Total sin filtro",
            f"{total_co_raw:,}",
            help="Total de check-outs antes de aplicar filtros"
        )
        st.metric(
            "Total con filtro",
            f"{total_co_filtered:,}",
            delta=f"-{diff_co:,}",
            delta_color="inverse",
            help="Total de check-outs después de aplicar filtros"
        )
        if total_co_raw > 0:
            percentage_co = (diff_co / total_co_raw) * 100
            st.metric(
                "% Excluido",
                f"{percentage_co:.1f}%"
            )

    with col_s3:
        st.markdown("**Coincidencias (Prioridad)**")
        total_prio_raw = reservations_raw['coincidencias'].sum()
        total_prio_filtered = reservations['coincidencias'].sum()
        diff_prio = total_prio_raw - total_prio_filtered

        st.metric(
            "Total sin filtro",
            f"{total_prio_raw:,}",
            help="Total de coincidencias antes de aplicar filtros"
        )
        st.metric(
            "Total con filtro",
            f"{total_prio_filtered:,}",
            delta=f"-{diff_prio:,}",
            delta_color="inverse",
            help="Total de coincidencias después de aplicar filtros"
        )
        if total_prio_raw > 0:
            percentage_prio = (diff_prio / total_prio_raw) * 100
            st.metric(
                "% Excluido",
                f"{percentage_prio:.1f}%"
            )

    # Tabla comparativa detallada
    st.markdown("---")
    st.markdown("##### 📋 Tabla Comparativa Detallada")

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

    # Botón de descarga
    csv_comparison = comparison_table.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="⬇️ Descargar Comparativa (CSV)",
        data=csv_comparison,
        file_name=f"comparativa_filtros_{datetime.date.today()}.csv",
        mime="text/csv",
        use_container_width=True
    )

    # Insights finales
    if filter_enabled:
        total_excluded_all = diff_ci + diff_co
        st.success(
            f"✅ Los filtros están excluyendo **{total_excluded_all:,} limpiezas** en total ({diff_ci:,} check-ins + {diff_co:,} check-outs)")
    else:
        st.info("ℹ️ Los filtros están desactivados. Actívalos desde la barra lateral para ver el impacto.")

# --- Footer ---
st.divider()
st.caption(f"🕒 Última actualización: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.caption("💡 Los listings que contengan '4991' u 'orange' están excluidos automáticamente")

