import io
import pandas as pd
import streamlit as st
from babel.numbers import format_currency

from services.storage import load_csv, save_csv, get_path
from process_functions import monetizacion_v0 as mon


# Nombres de los archivos persistentes
HISTORIAL_FILE = "airbnb_reservations_paid_historico.csv"
HISTORIAL_PAYOUT_FILE = "airbnb_payouts_historico.csv"
HISTORIAL_MONETIZACION_FILE = "monetizaciones.csv"


def run():
    st.title("Monetizaciones")

    CUENTAS = ['PRINCIPAL', 'RH', 'COLONIA', 'BOULERVARD']

    # ----------------- SIDEBAR: ACTUALIZAR HISTORIAL AIRBNB -----------------
    with st.sidebar:
        st.subheader("Actualizar historial Airbnb")

        airbnb_file = st.file_uploader(
            "Sube uno o más archivos CSV de lotes",
            type=["csv"],
            accept_multiple_files=False,
        )

        if airbnb_file:
            cuenta = st.selectbox("Selecciona la cuenta", CUENTAS)

            if st.button("Actualizar historial"):
                clean_df = mon.fix_raw_data(airbnb_file, cuenta)

                updated_historical = mon.update_airbnb_historical(
                    clean_df,
                    get_path(HISTORIAL_FILE)
                )
                save_csv(HISTORIAL_FILE, updated_historical)

                payouts = mon.update_payout(
                    updated_historical,
                    get_path(HISTORIAL_PAYOUT_FILE)
                )
                save_csv(HISTORIAL_PAYOUT_FILE, payouts)

                st.success("Historial de payouts actualizado.")
        else:
            st.warning("NO SE HA CARGADO ARCHIVO DE AIRBNB")

    # ----------------- CARGAR HISTORIALES -----------------
    airbnb_historical = load_csv(HISTORIAL_FILE)
    payouts = load_csv(HISTORIAL_PAYOUT_FILE)

    # ----------------- AÑADIR PAYOUT MANUAL (STRIPE) -----------------
    st.subheader("Solo para Stripe - completar pagos")

    stripe_nums = (
        payouts["Código de referencia"]
        .astype(str)
        .str.extract(r"^Stripe-(\d+)$", expand=False)
        .dropna()
    )

    last_num = max(stripe_nums.astype(int).max(), 16) if not stripe_nums.empty else 16
    next_stripe_code = f"Stripe-{last_num + 1}"

    with st.expander("Solo para Stripe"):
        with st.form("form_nuevo_payout"):
            st.markdown(
                f"**Código de referencia asignado automáticamente:** `{next_stripe_code}`"
            )

            fecha_nueva = st.date_input("Fecha de payout")
            total_pagado_nuevo = st.number_input("Total pagado (USD)", min_value=0.0)
            monto_nuevo = st.number_input("Monto (COP)", min_value=0.0)
            numero_reservas_nueva = st.number_input("Número de reservas", min_value=0.0)

            if st.form_submit_button("Guardar payout manual"):
                new_row = {
                    "id_accival": "pre_accival",
                    "Código de referencia": next_stripe_code,
                    "Monto": monto_nuevo,
                    "Total pagado": total_pagado_nuevo,
                    "Fecha": fecha_nueva.strftime("%Y-%m-%d"),
                    "Cantidad reservas": numero_reservas_nueva,
                    "fuente": "PRINCIPAL",
                }

                payouts = pd.concat([payouts, pd.DataFrame([new_row])], ignore_index=True)
                save_csv(HISTORIAL_PAYOUT_FILE, payouts)

                st.success(f"Payout manual agregado con código {next_stripe_code}")

    # ----------------- EDITAR id_accival -----------------
    st.subheader("Transacciones pendientes de monetización")
    st.caption("Actualizar ID Accival cuando se monetiza la transacción")

    payouts['id_accival'] = payouts['id_accival'].astype(str)

    df_editables = payouts[
        (payouts['id_accival'] == '') |
        (payouts['id_accival'].str.startswith('pre_accival'))
    ].copy()

    df_editables = df_editables[
        ['id_accival'] + [c for c in df_editables.columns if c != 'id_accival']
    ]

    df_editado = st.data_editor(
        df_editables,
        column_config={"id_accival": st.column_config.TextColumn("ID Accival")},
        disabled=[c for c in df_editables.columns if c != 'id_accival'],
        num_rows="fixed",
    )

    if st.button("Guardar cambios"):
        for idx, row in df_editado.iterrows():
            payouts.loc[payouts['Código de referencia'] == row['Código de referencia'], 'id_accival'] = row['id_accival']

        save_csv(HISTORIAL_PAYOUT_FILE, payouts)
        st.success("Cambios guardados correctamente.")

    # ----------------- ACTUALIZAR MONETIZACIÓN -----------------
    monet = mon.update_monetizacion(payouts, get_path(HISTORIAL_MONETIZACION_FILE))

    # Sincronizar
    monet["id_accival"] = monet["id_accival"].astype(str)
    payouts["id_accival"] = payouts["id_accival"].astype(str)

    pre_refs_payouts = payouts[payouts["id_accival"].str.startswith("pre_accival")]["id_accival"]

    if pre_refs_payouts.empty:
        monet = monet[~monet["id_accival"].str.startswith("pre_accival")]
    else:
        monet = monet[~(
            monet["id_accival"].str.startswith("pre_accival") &
            ~monet["id_accival"].isin(pre_refs_payouts)
        )]

    if "fecha" in monet.columns:
        monet["fecha"] = pd.to_datetime(monet["fecha"], errors="coerce")
        monet = monet.sort_values("fecha").drop_duplicates("id_accival", keep="last")

    save_csv(HISTORIAL_MONETIZACION_FILE, monet)

    # ----------------- LISTA DE MONETIZACIONES -----------------
    st.subheader("Registro histórico de monetizaciones")
    monet = monet.sort_values("fecha", ascending=False).reset_index(drop=True)
    st.dataframe(monet)

    # Editar solo sin fecha
    sin_fecha = monet[monet["fecha"].isna()].copy()
    monet_editado = st.data_editor(sin_fecha, num_rows="fixed")

    if st.button("Guardar cambios monetizaciones"):
        monet_updated = monet.copy()
        for idx, row in monet_editado.iterrows():
            monet_updated.loc[idx] = row
        save_csv(HISTORIAL_MONETIZACION_FILE, monet_updated)
        st.success("Cambios guardados correctamente.")

    # ----------------- RESÚMENES Y MÉTRICAS -----------------
    df_pre = monet[monet['id_accival'].str.startswith('pre_accival')]
    df_mon = monet[monet['id_accival'].str.startswith('accival')].copy()
    df_mon['fecha'] = pd.to_datetime(df_mon['fecha'])

    accival_trans = df_mon.groupby(df_mon['fecha'].dt.to_period('M'))['id_accival'].count().reset_index()

    avg_trm_month = round(df_mon.groupby(df_mon['fecha'].dt.to_period('M'))['trm'].mean(), 0).reset_index()

    df_mensual = df_mon.groupby(df_mon['fecha'].dt.to_period('M'))[['monto_usd', 'monto_cop', 'costo']].sum().reset_index()

    df_mensual['monto_usd'] = df_mensual['monto_usd'].apply(lambda x: f"${x:,.0f}")
    df_mensual['monto_cop'] = df_mensual['monto_cop'].apply(lambda x: f"${x:,.0f}")
    df_mensual['costo'] = df_mensual['costo'].apply(lambda x: f"${x:,.0f}")

    df_merged = df_mensual.merge(accival_trans, on='fecha', how='left').merge(avg_trm_month, on='fecha', how='left')

    st.header("Histórico Mensual")
    st.write(df_merged)
    st.caption("Monetizaciones desde Mayo 2025")

    st.metric("MONETIZADO USD", format_currency(df_mon['monto_usd'].sum(), "COP", locale='es_CO'))
    st.metric("MONETIZADO COP", format_currency(df_mon['monto_cop'].sum(), "COP", locale='es_CO'))
    st.metric("POR MONETIZAR", format_currency(df_pre['monto_usd'].sum(), "COP", locale='es_CO'))
    st.metric("COSTO", format_currency(monet['costo'].sum(), "COP", locale='es_CO'))
    st.metric("TRM PROMEDIO", format_currency(monet['trm'].mean(), "COP", locale='es_CO'))
    st.metric("INGRESO POTENCIAL", format_currency(df_pre['monto_usd'].sum() * monet['trm'].mean(), "COP", locale='es_CO'))

    # ----------------- EXPORT PRE_ACCIVAL -----------------
    df_pre_payout = payouts[payouts['id_accival'].str.startswith('pre_accival')][
        ['id_accival', 'Fecha', 'Código de referencia', 'Total pagado']
    ]

    if not df_pre_payout.empty:
        buffer = io.BytesIO()
        df_pre_payout.to_excel(buffer, index=False, sheet_name='pre_accival')
        buffer.seek(0)

        st.download_button(
            label="📥 Descargar Excel de pre_accival",
            data=buffer,
            file_name="pre_accival_transacciones.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.info("No hay filas con 'pre_accival' para exportar.")

    # ----------------- PAGOS -----------------
    st.subheader("Payouts")
    st.caption("Listado de todos los payouts enviados con su id de la monetización de Accival")
    st.dataframe(payouts)

    with st.expander("Cambios en caso de error para Payouts"):
        payouts_editado = st.data_editor(
            payouts,
            disabled=[col for col in payouts.columns if col != "id_accival"],
            num_rows="fixed",
        )

        if st.button("Guardar cambios (Payouts)"):
            save_csv(HISTORIAL_PAYOUT_FILE, payouts_editado)
            st.success("Cambios en payouts guardados correctamente.")

    # ----------------- GRÁFICOS -----------------
    st.subheader("Gráficas de comportamiento")
    st.line_chart(monet, x="fecha", y=["trm", "trm_dia"])
    st.line_chart(monet, x="fecha", y="monto_usd")
    st.bar_chart(monet, x="fecha", y="monto_cop")
