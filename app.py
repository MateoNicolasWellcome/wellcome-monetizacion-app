import io
from pathlib import Path
import shutil
from babel.numbers import format_currency
import pandas as pd
import streamlit as st

from process_functions import monetizacion_v0 as mon


BASE_DIR = Path(__file__).parent
SEED_DIR = BASE_DIR / "seed_data"

DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_FILES = [
    "airbnb_reservations_paid_historico.csv",
    "airbnb_payouts_historico.csv",
    "monetizaciones.csv",
]

# Si el volumen está vacío, copiamos los CSV semilla una sola vez
for fname in CSV_FILES:
    dst = DATA_DIR / fname
    if not dst.exists():
        src = SEED_DIR / fname
        if src.exists():
            shutil.copy(src, dst)

HISTORIAL_PATH = DATA_DIR / "airbnb_reservations_paid_historico.csv"
HISTORIAL_PAYOUT_PATH = DATA_DIR / "airbnb_payouts_historico.csv"
HISTORIAL_MONETIZACION_PATH = DATA_DIR / "monetizaciones.csv"

st.title("Monetizaciones")


CUENTAS = ['PRINCIPAL', 'RH', 'COLONIA', 'BOULERVARD']

# ----------------- SIDEBAR: ACTUALIZAR HISTORIAL AIRBNB -----------------
with st.sidebar:
    st.subheader("Actualizar historial Airbnb")
    airbnb_file = st.file_uploader(
        "Sube uno o más archivos CSV de lotes",
        type=["csv"],
        accept_multiple_files=False
    )

    if airbnb_file:
        cuenta = st.selectbox("Selecciona la cuenta", CUENTAS)

        if st.button("Actualizar historial"):
            clean_df = mon.fix_raw_data(airbnb_file, cuenta)
            updated_historical = mon.update_airbnb_historical(
                clean_df,
                HISTORIAL_PATH
            )
            updated_historical.to_csv(HISTORIAL_PATH, index=False)

            payouts = mon.update_payout(
                updated_historical,
                HISTORIAL_PAYOUT_PATH
            )
            payouts.to_csv(HISTORIAL_PAYOUT_PATH, index=False)

            st.success("Historial de payouts actualizado.")
    else:
        st.warning("NO SE HA CARGADO ARCHIVO DE AIRBNB")

# Cargamos siempre los historiales (ya sean iniciales o actualizados)
airbnb_historical = pd.read_csv(HISTORIAL_PATH)
payouts = pd.read_csv(HISTORIAL_PAYOUT_PATH)

# ----------------- AÑADIR PAYOUT MANUAL (STRIPE) -----------------
st.subheader("Solo para Stripe - completar pagos")

stripe_nums = (
    payouts["Código de referencia"]
    .astype(str)
    .str.extract(r"^Stripe-(\d+)$", expand=False)
)
stripe_nums = stripe_nums.dropna()

if not stripe_nums.empty:
    last_num = stripe_nums.astype(int).max()
    last_num = max(last_num, 16)
else:
    last_num = 16

next_stripe_code = f"Stripe-{last_num + 1}"

with st.expander("Solo para Stripe"):
    with st.form("form_nuevo_payout"):
        st.markdown(
            f"**Código de referencia asignado automáticamente:** "
            f"`{next_stripe_code}`"
        )

        fecha_nueva = st.date_input("Fecha de payout")
        total_pagado_nuevo = st.number_input(
            "Total pagado (USD)", min_value=0.0, step=1.0
        )
        monto_nuevo = st.number_input(
            "Monto (COP)", min_value=0.0, step=1.0
        )
        numero_reservas_nueva = st.number_input(
            "Número de reservas", min_value=0.0, step=1.0
        )
        cuenta_nueva = "PRINCIPAL"
        id_accival_nueva = "pre_accival"

        submit_nuevo = st.form_submit_button("Guardar payout manual")

        if submit_nuevo:
            new_row = {col: None for col in payouts.columns}

            if "id_accival" in new_row:
                new_row["id_accival"] = id_accival_nueva
            if "Código de referencia" in new_row:
                new_row["Código de referencia"] = next_stripe_code
            if "Monto" in new_row:
                new_row["Monto"] = monto_nuevo
            if "Total pagado" in new_row:
                new_row["Total pagado"] = total_pagado_nuevo
            if "Fecha" in new_row:
                new_row["Fecha"] = fecha_nueva.strftime("%Y-%m-%d")
            if "Cantidad reservas" in new_row:
                new_row["Cantidad reservas"] = numero_reservas_nueva
            if "fuente" in new_row:
                new_row["fuente"] = cuenta_nueva

            payouts = pd.concat(
                [payouts, pd.DataFrame([new_row])],
                ignore_index=True
            )
            payouts.to_csv(HISTORIAL_PAYOUT_PATH, index=False)

            st.success(
                f"Payout manual agregado con código de referencia "
                f"{next_stripe_code}"
            )

# ----------------- EDITAR id_accival -----------------
st.subheader("Transacciones pendientes de monetización")
st.caption("El campo de ID accival  se tiene que actualizar cuando esa transacción se ha monetizado, con el id correspondiente")

payouts['id_accival'] = payouts['id_accival'].astype(str)

df_editables = payouts[
    (payouts['id_accival'] == '') |
    (payouts['id_accival'].str.startswith('pre_accival'))
].copy()

cols = ['id_accival'] + [
    col for col in df_editables.columns if col != 'id_accival'
]
df_editables = df_editables[cols]

df_editado = st.data_editor(
    df_editables,
    column_config={
        "id_accival": st.column_config.TextColumn("ID Accival")
    },
    disabled=[col for col in df_editables.columns if col != 'id_accival'],
    num_rows="fixed"
)

if st.button("Guardar cambios"):
    df_final = payouts.copy()
    for idx, row in df_editado.iterrows():
        df_final.loc[
            df_final['Código de referencia'] == row['Código de referencia'],
            'id_accival'
        ] = row['id_accival']

    df_final.to_csv(HISTORIAL_PAYOUT_PATH, index=False)
    st.success("Cambios guardados correctamente.")

# ----------------- ACTUALIZAR MONETIZACIÓN -----------------
monet = mon.update_monetizacion(payouts, HISTORIAL_MONETIZACION_PATH)

# Sincronizar monetizaciones con payouts
monet["id_accival"] = monet["id_accival"].astype(str)
payouts["id_accival"] = payouts["id_accival"].astype(str)

pre_refs_payouts = payouts.loc[
    payouts["id_accival"].str.startswith("pre_accival"),
    "id_accival"
].astype(str)

if pre_refs_payouts.empty:
    monet = monet[~monet["id_accival"].str.startswith("pre_accival")].copy()
else:
    monet = monet[~(
        monet["id_accival"].str.startswith("pre_accival")
        & ~monet["id_accival"].astype(str).isin(pre_refs_payouts)
    )].copy()

if "fecha" in monet.columns:
    monet["fecha"] = pd.to_datetime(monet["fecha"], errors="coerce")
    monet = (
        monet.sort_values("fecha")
             .drop_duplicates(subset=["id_accival"], keep="last")
    )

monet.to_csv(HISTORIAL_MONETIZACION_PATH, index=False)

# ----------------- LISTADO Y EDICIÓN DE MONETIZACIONES -----------------
st.subheader("Registro histórico de monetizaciones")
st.caption("Aquí se debe actualizar con información adicional cuando se accival envía la liquidacion")
monet = monet.sort_values("fecha", ascending=False).reset_index(drop=True)
st.dataframe(monet)

sin_fecha = monet[
    monet["fecha"].isna() | (monet["fecha"].astype(str).str.strip() == "")
].copy()


monet_editado = st.data_editor(
    sin_fecha,
    num_rows="fixed"
)


if st.button("Guardar cambios monetizaciones"):
    monet_updated = monet.copy()
    for idx, row in monet_editado.iterrows():
        monet_updated.loc[idx] = row
    monet_updated.to_csv(HISTORIAL_MONETIZACION_PATH, index=False)
    st.success("Cambios en monetizaciones guardados correctamente.")

# ----------------- MÉTRICAS Y RESÚMENES -----------------
df_pre = monet[monet['id_accival'].str.startswith('pre_accival')].copy()
df_mon = monet[monet['id_accival'].str.startswith('accival')].copy()

df_mon['fecha'] = pd.to_datetime(df_mon['fecha'])

accival_trans = df_mon.groupby(df_mon['fecha'].dt.to_period('M'))[
    'id_accival'
].count().reset_index()

avg_trm_month = round(
    df_mon.groupby(df_mon['fecha'].dt.to_period('M'))['trm'].mean(),
    0
).reset_index()

df_mensual = df_mon.groupby(df_mon['fecha'].dt.to_period('M'))[
    ['monto_usd', 'monto_cop', 'costo']
].sum().reset_index()

avg_cost_month = df_mensual['monto_cop'] / df_mensual['costo']

df_mensual['monto_usd'] = df_mensual['monto_usd'].apply(
    lambda x: f"${x:,.0f}"
)
df_mensual['monto_cop'] = df_mensual['monto_cop'].apply(
    lambda x: f"${x:,.0f}"
)
df_mensual['costo'] = df_mensual['costo'].apply(
    lambda x: f"${x:,.0f}"
)

df_merged = pd.merge(df_mensual, accival_trans, on='fecha', how='left')
df_merged_f = pd.merge(df_merged, avg_trm_month, on='fecha', how='left')
st.header("Historico Mensual")
st.write(df_merged_f)
st.caption("Monetizaciones desde Mayo 2025")

st.metric(
    "MONETIZADO USD ",
    format_currency(df_mon['monto_usd'].sum(), "COP", locale='es_CO')
)
st.metric(
    "MONETIZADO COP ",
    format_currency(df_mon['monto_cop'].sum(), "COP", locale='es_CO')
)
st.metric(
    "POR MONETIZAR",
    format_currency(df_pre['monto_usd'].sum(), "COP", locale='es_CO')
)
st.metric(
    "COSTO",
    format_currency(monet['costo'].sum(), "COP", locale='es_CO')
)
st.metric(
    "TRM PROMEDIO",
    format_currency(monet['trm'].mean(), "COP", locale='es_CO')
)
st.metric(
    "INGRESO POTENCIAL",
    format_currency(df_pre['monto_usd'].sum() * monet['trm'].mean(),
                    "COP", locale='es_CO')
)

df_pre_payout = payouts[payouts['id_accival'].str.startswith('pre_accival')]
df_pre_payout = df_pre_payout[
    ['id_accival', 'Fecha', 'Código de referencia', 'Total pagado']
]

if not df_pre_payout.empty:
    buffer = io.BytesIO()
    df_pre_payout.to_excel(
        buffer,
        index=False,
        sheet_name='pre_accival'
    )
    buffer.seek(0)

    st.download_button(
        label="📥 Descargar Excel de pre_accival",
        data=buffer,
        file_name="pre_accival_transacciones.xlsx",
        mime=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        )
    )
else:
    st.info("No hay filas con 'pre_accival' para exportar.")

st.subheader("Payouts")
st.caption("Listado de todos los payouts enviados con su id de la monetización de Accival")
st.dataframe(payouts)

with st.expander("Cambios en caso de error para Payouts"):
    editable_cols = ["id_accival"]

    payouts_editado = st.data_editor(
        payouts,
        disabled=[col for col in payouts.columns if col not in editable_cols],
        num_rows="fixed"
    )

    if st.button("Guardar cambios (Payouts)"):
        payouts_editado.to_csv(HISTORIAL_PAYOUT_PATH, index=False)
        st.success("Cambios en payouts guardados correctamente.")

st.subheader("Gráficas de comportamiento a traves del tiempo")
st.line_chart(monet, x="fecha", y=["trm", "trm_dia"])
st.line_chart(monet, x="fecha", y="monto_usd")
st.bar_chart(monet, x="fecha", y="monto_cop")
