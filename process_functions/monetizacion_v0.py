import os
import numpy as np
import pandas as pd


def fix_raw_data(csv_airbnb_file, name_source):
    df = pd.read_csv(csv_airbnb_file)
    need_columns = ['Fecha', 'Tipo', 'Código de confirmación', 'Detalles', 'Código de referencia', 'Moneda', 'Monto',
                    'Total pagado']
    df = df[need_columns]
    df['fuente'] = name_source
    df['Fecha'] = pd.to_datetime(df['Fecha'], format='%m/%d/%Y')
    df['Total pagado'] = df['Total pagado'].replace(to_replace=np.nan, method='ffill', inplace=False)
    df['Código de referencia'] = df['Código de referencia'].replace(to_replace=np.nan, method='ffill',inplace=False)
    return df


def update_airbnb_historical(df_nuevo, nombre_archivo_acumulado):
    if os.path.exists(nombre_archivo_acumulado):
        df_acumulado = pd.read_csv(nombre_archivo_acumulado, parse_dates=['Fecha'])
    else:
        df_acumulado = pd.DataFrame(columns=df_nuevo.columns)
    df_nuevo = df_nuevo[~df_nuevo['Tipo'].str.contains('Payout', case=False, na=False)]
    df_final = pd.concat([df_acumulado, df_nuevo], ignore_index=True)
    df_final.drop_duplicates(inplace=True)
    return df_final


def update_payout(df, file_historico):
    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    df['Fecha'] = df['Fecha'].dt.date
    df_transacciones = df.groupby('Código de referencia').agg({
        'Monto': 'sum',
        'Total pagado': 'first',
        'Fecha': 'first',
        'Código de referencia': 'count',  # cuenta las filas por grupo
        'fuente': 'first'
    }).rename(columns={'Código de referencia': 'Cantidad reservas'}).reset_index()
    df_transacciones = df_transacciones.sort_values(by='Fecha')
    df_transacciones['id_accival'] = 'pre_accival'

    if os.path.exists(file_historico):
        df_acumulado = pd.read_csv(file_historico, parse_dates=['Fecha'])
    else:
        df_acumulado = pd.DataFrame(columns=df_transacciones.columns)
    codigos_existentes = set(df_acumulado['Código de referencia'].unique())
    df_transacciones = df_transacciones[~df_transacciones['Código de referencia'].isin(codigos_existentes)]
    df_final = pd.concat([df_acumulado, df_transacciones], ignore_index=True)
    df_final.drop_duplicates(inplace=True)
    return df_final


def update_monetizacion(df,archivo_monetizaciones):
    df_validos = df.dropna(subset=['id_accival'])
    df_nuevo = df_validos.groupby(['id_accival']).agg({
        'Total pagado': 'sum',
        'Código de referencia': 'count'
    }).reset_index()

    df_nuevo.rename(columns={
        'Fecha': 'fecha_monetizacion',
        'Total pagado': 'monto_usd',
        'Código de referencia': 'num_transacciones'
    }, inplace=True)

    df_nuevo['trm'] = ''
    df_nuevo['monto_cop'] = ''
    df_nuevo['costo'] = ''

    if os.path.exists(archivo_monetizaciones):
        df_existente = pd.read_csv(archivo_monetizaciones)

        df_actualizado = df_existente.merge(
            df_nuevo[['id_accival', 'monto_usd', 'num_transacciones']],
            on='id_accival',
            how='outer',
            suffixes=('', '_nuevo')
        )

        df_actualizado['monto_usd'] = df_actualizado['monto_usd_nuevo'].combine_first(df_actualizado['monto_usd'])
        df_actualizado['num_transacciones'] = df_actualizado['num_transacciones_nuevo'].combine_first(
            df_actualizado['num_transacciones'])

        df_actualizado.drop(columns=['monto_usd_nuevo', 'num_transacciones_nuevo'], inplace=True)

        df_actualizado.drop_duplicates(subset='id_accival', keep='last', inplace=True)
    else:
        df_actualizado = df_nuevo
    df_actualizado.to_csv(archivo_monetizaciones, index=False)
    print(df_actualizado.columns.tolist())
    return df_actualizado



