import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO


def run():
    st.title("Contabilidad")
    st.caption("Validación, Facturación y Pago a Propietarios")

    # =============================================================================
    # 1. VALIDACIÓN Y LIMPIEZA DE RESERVAS
    # =============================================================================
    st.subheader("1. Validación de Reservas")
    st.caption("Se genear un archivo descargable de las reservas que tienen errores. Corregirlas en Guesty")

    tol = 0.01
    exclude_owner = "Mauricio Duarte"
    max_rows = 300

    with st.sidebar:
        st.header("Subir documento")
        uploaded = st.file_uploader(
            "Subir el archivo de transacciones CSV",
            type=["csv", "xlsx", "xls"]
        )
        if not uploaded:
            st.info("Subir un archivo para comenzar")
            return   # ← en páginas se usa return, no st.stop()

    @st.cache_data(show_spinner="Leyendo archivo...")
    def read_file(f):
        return pd.read_excel(f) if f.name.lower().endswith(('.xlsx', '.xls')) else pd.read_csv(f)

    raw = read_file(uploaded)

    required_cols = {
        "ownerName", "listingNickname", "reservationConfirmationCode",
        "amount", "chargeCode", "revenueRecognitionDate"
    }
    if missing := required_cols - set(raw.columns):
        st.error(f"Faltan columnas: {', '.join(sorted(missing))}")
        return

    # --- Pipeline de validación ---
    @st.cache_data(show_spinner="Analizando reservas...")
    def procesar_todo(_df: pd.DataFrame, tol: float, exclude: str | None):
        df = _df.copy()
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * -1
        df["revenueRecognitionDate"] = pd.to_datetime(df["revenueRecognitionDate"], errors="coerce")

        if exclude:
            df = df[~df["ownerName"].astype(str).str.contains(exclude, case=False, na=False)]

        df["year_month"] = df["revenueRecognitionDate"].dt.to_period("M").astype(str)
        con_reserva = df[df["reservationConfirmationCode"].notna()].copy()

        if con_reserva.empty:
            df["es_valida"] = True
            df["motivo_rechazo"] = None
            return df, df.copy(), pd.DataFrame()

        grouped = con_reserva.groupby(["ownerName", "listingNickname", "reservationConfirmationCode"])

        suma = grouped["amount"].sum().to_frame("suma_total").reset_index()
        suma["suma_red"] = np.where(suma["suma_total"].abs() < tol, 0.0, suma["suma_total"])

        codigos = grouped["chargeCode"].apply(
            lambda x: sorted({str(c).strip().upper() for c in x.dropna() if pd.notna(c)})
        ).to_frame("codes").reset_index()
        codigos["codes_str"] = codigos["codes"].apply(", ".join)
        codigos["tiene_minimos"] = codigos["codes"].apply({"AF", "VATOC", "CMS"}.issubset)

        base = suma.merge(codigos, on=["ownerName", "listingNickname", "reservationConfirmationCode"])

        condiciones = [
            (base["suma_red"] == 0, "Suma ≈ 0"),
            (base["suma_red"] < 0, "Suma negativa"),
            ((base["suma_red"] < 0) & (~base["tiene_minimos"]), "Suma negativa + faltan mínimos"),
            (~base["tiene_minimos"], "Faltan códigos mínimos"),
        ]
        motivo = pd.Series("Válida", index=base.index)
        for cond, texto in condiciones:
            motivo = motivo.mask(cond, texto)
        base["motivo_rechazo"] = motivo

        malas_summary = base[base["motivo_rechazo"] != "Válida"].copy()
        malas_summary["es_canal"] = malas_summary["reservationConfirmationCode"].astype(str).str.startswith(("BC-", "EXP-"))
        malas_summary["sin_oc"] = ~malas_summary["codes"].apply(lambda x: "OC" in x)
        malas_summary["alerta_costo_fin"] = malas_summary["es_canal"] & malas_summary["sin_oc"]

        malas_summary = malas_summary.rename(columns={"codes_str": "códigos_presentes"})[
            ["reservationConfirmationCode", "ownerName", "listingNickname", "suma_total",
             "códigos_presentes", "motivo_rechazo", "tiene_minimos", "alerta_costo_fin"]
        ]

        reservas_malas = set(malas_summary["reservationConfirmationCode"])
        df["es_valida"] = ~df["reservationConfirmationCode"].isin(reservas_malas)
        df["motivo_rechazo"] = df["reservationConfirmationCode"].map(
            malas_summary.set_index("reservationConfirmationCode")["motivo_rechazo"]
        )

        df_limpio = df[df["es_valida"]].drop(columns=["es_valida", "motivo_rechazo", "year_month"], errors="ignore").copy()

        return df, df_limpio, malas_summary

    df_full, df_limpio, df_malas_summary = procesar_todo(raw, tol, exclude_owner)

    # Guardar en session_state
    st.session_state["df_full"] = df_full
    st.session_state["df_limpio"] = df_limpio
    st.session_state["df_malas_summary"] = df_malas_summary
    st.session_state["reservas_validas"] = set(df_limpio["reservationConfirmationCode"].dropna().unique())

    # Métricas
    total_res = raw["reservationConfirmationCode"].nunique()
    validas_res = len(st.session_state.reservas_validas)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total reservas", f"{total_res:,}")
    c2.metric("Válidas", f"{validas_res:,}")
    c3.metric("Con error", f"{len(df_malas_summary):,}", delta=f"-{len(df_malas_summary):,}")
    c4.metric("Alertas BC-/EXP- sin OC", f"{df_malas_summary['alerta_costo_fin'].sum():,}")

    # Tabla de errores
    st.subheader("Reservas con error – Archivo para corrección")
    if df_malas_summary.empty:
        st.success("¡Todas las reservas están perfectas!")
    else:
        st.dataframe(df_malas_summary.head(max_rows), use_container_width=True)

    # Descarga errores
    if not df_malas_summary.empty:
        st.divider()
        fecha = pd.Timestamp('today').strftime('%Y%m%d')
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df_malas_summary.to_excel(writer, sheet_name="Errores", index=False)
        st.download_button(
            "Descargar reservas con errores (Excel)",
            data=output.getvalue(),
            file_name=f"errores_reservas_{fecha}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    st.success(f"Validación completa → {len(df_limpio):,} transacciones limpias listas")

    # =============================================================================
    # 2. FACTURACIÓN A PROPIETARIOS
    # =============================================================================
    st.divider()
    st.subheader("2. Facturación a Propietarios")
    st.caption("Tener cuidado con propietarios auditados aparte: Oragen, D90")
    st.caption("Un paso después de descargar el archivo es agrupar: Colonia, Nook")

    df = df_limpio.copy()
    df['chargeCode'] = df['chargeCode'].astype(str).str.strip().str.upper()
    df['ownerName'] = df['ownerName'].astype(str).str.strip().str.title()
    df['listingNickname'] = df['listingNickname'].astype(str).str.strip()

    df_facturable = df[df['chargeCode'].isin(['CMS', 'VATOC'])].copy()

    cms = df_facturable[df_facturable['chargeCode']=='CMS'] \
        .groupby(['ownerName','listingNickname'])['amount'].sum().reset_index(name='CMS_Neto')

    vatoc = df_facturable[df_facturable['chargeCode']=='VATOC'] \
        .groupby(['ownerName','listingNickname'])['amount'].sum().reset_index(name='IVA_VATOC')

    facturacion = pd.merge(cms, vatoc, on=['ownerName','listingNickname'], how='outer').fillna(0)
    facturacion['Total_a_Facturar'] = facturacion['CMS_Neto'] + facturacion['IVA_VATOC']
    facturacion = facturacion.sort_values(['ownerName','listingNickname']).reset_index(drop=True)

    st.dataframe(facturacion, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Neto (CMS)", f"${-1*facturacion['CMS_Neto'].sum():,.2f}")
    c2.metric("Total IVA (VATOC)", f"${-1*facturacion['IVA_VATOC'].sum():,.2f}")
    c3.metric("Total a Facturar", f"${-1*facturacion['Total_a_Facturar'].sum():,.2f}")

    @st.cache_data
    def excel_facturacion_con_signo_contrario(df_excel):
        df_out = df_excel.copy()
        for col in ['CMS_Neto','IVA_VATOC','Total_a_Facturar']:
            df_out[col] = -df_out[col]

        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_out.to_excel(writer, sheet_name='Facturacion', index=False)
            workbook = writer.book
            worksheet = writer.sheets['Facturacion']
            fmt_money = workbook.add_format({'num_format': '#,##0.00'})
            fmt_header = workbook.add_format({'bold': True, 'bg_color': '#E3F2FD'})
            fmt_total = workbook.add_format({'bold': True, 'bg_color': '#FFF3E0', 'num_format': '#,##0.00'})

            worksheet.set_column('A:B', 35)
            worksheet.set_column('C:E', 20, fmt_money)
            worksheet.set_row(0, None, fmt_header)

            last = len(df_out) + 2
            worksheet.write(last, 0, "TOTAL GENERAL", fmt_header)
            for i, col in enumerate(['CMS_Neto','IVA_VATOC','Total_a_Facturar'], 2):
                worksheet.write(last, i, df_out[col].sum(), fmt_total)

        return output.getvalue()

    st.download_button(
        "Descargar Facturación (Excel - signo contrario)",
        data=excel_facturacion_con_signo_contrario(facturacion),
        file_name=f"FACTURACION_propietarios_{pd.Timestamp('today').strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # =============================================================================
    # 3. PAGO NETO A PROPIETARIOS
    # =============================================================================
    st.divider()
    st.subheader("3. Pago Neto a Propietarios")
    st.caption("Cuidado: excluir PO y revisar pagos parciales del mes anterior")

    df_sin_po = df[df['chargeCode'] != 'PO'].copy()

    pago = df_sin_po.groupby(['ownerName', 'listingNickname'], as_index=False)['amount'].sum()
    pago['A_Transferir'] = pago['amount'].abs().round(2)
    pago_final = pago[pago['A_Transferir'] > 0][['ownerName','listingNickname','A_Transferir']]
    pago_final = pago_final.sort_values(['ownerName', 'listingNickname']).reset_index(drop=True)

    st.dataframe(pago_final, use_container_width=True)

    st.metric("Total a Transferir", f"${pago_final['A_Transferir'].sum():,.2f}")

    @st.cache_data
    def excel_pago(df):
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Pago_Propietarios', index=False)
            ws = writer.sheets['Pago_Propietarios']
            fmt_money = writer.book.add_format({'num_format': '#,##0.00'})
            fmt_header = writer.book.add_format({'bold': True, 'bg_color': '#E3F2FD'})
            ws.set_column('A:A', 45)
            ws.set_column('B:B', 22, fmt_money)
            ws.set_row(0, None, fmt_header)
        return output.getvalue()

    st.download_button(
        "Descargar Pago a Propietarios (Excel)",
        data=excel_pago(pago_final),
        file_name=f"PAGO_propietarios_{pd.Timestamp('today').strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
