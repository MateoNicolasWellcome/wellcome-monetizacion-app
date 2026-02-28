"""
services/guesty_view_endpoint.py
─────────────────────────────────
Configuración de las vistas de Guesty utilizadas por el plan de limpiezas.

Las vistas ("reservations-reports") son filtros guardados en Guesty que
pre-seleccionan reservas según criterios específicos (check-ins o check-outs
en Bogotá, propiedades activas, etc.).

Para agregar una nueva vista:
  1. Crear el filtro en Guesty → Reservations → Reports → Save view
  2. Copiar el ID desde la URL y agregar una constante aquí
  3. Crear una función get_*_data() que use client.get_reservations_view()
"""

import pandas as pd

from services.guesty_client import GuestyClient

# ── IDs de vistas guardadas en Guesty ─────────────────────────────────────────
VIEW_ID_IN  = "67e4662ff62c503d30ac4b65"   # Check-ins Bogotá
VIEW_ID_OUT = "66e99b9d462a960d2e7ac304"   # Check-outs Bogotá


# ── Funciones de acceso ───────────────────────────────────────────────────────

def get_checkin_data(client: GuestyClient) -> pd.DataFrame:
    """
    Reservas con check-in próximo (vista de check-ins Bogotá).

    Args:
        client: instancia de GuestyClient con token válido

    Returns:
        DataFrame con columnas de la vista (checkInDate, listing.nickname, etc.)
    """
    return client.get_reservations_view(VIEW_ID_IN)


def get_checkout_data(client: GuestyClient) -> pd.DataFrame:
    """
    Reservas con check-out próximo (vista de check-outs Bogotá).

    Args:
        client: instancia de GuestyClient con token válido

    Returns:
        DataFrame con columnas de la vista (checkOutDate, listing.nickname, etc.)
    """
    return client.get_reservations_view(VIEW_ID_OUT)
