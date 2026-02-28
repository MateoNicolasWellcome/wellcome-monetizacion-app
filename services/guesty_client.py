"""
services/guesty_client.py
──────────────────────────
Cliente centralizado para la API de Guesty (Open API v1).

Sin dependencias de Streamlit — es Python puro y reutilizable con cualquier
framework web. Los errores se comunican via excepciones.

Uso:
    from services.guesty_api import get_guesty_token
    from services.guesty_client import GuestyClient

    token = get_guesty_token()            # lanza GuestyAuthError si falla
    client = GuestyClient(token)

    listings_df    = client.get_listings()
    reservas_df    = client.get_reservations(check_in_from="2025-01-01")
    calendario_df  = client.get_calendar("listing-id", "2025-01-01", "2025-03-31")
    view_df        = client.get_reservations_view("view-id-aqui")
"""

import logging
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE = "https://open-api.guesty.com/v1"
DEFAULT_TIMEOUT = 20        # segundos por petición
PAGE_SIZE = 100             # registros por página (máximo que acepta Guesty)


class GuestyAPIError(Exception):
    """Error genérico de la API de Guesty (HTTP o de red)."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GuestyClient:
    """
    Cliente HTTP para la Open API de Guesty.

    Responsabilidades:
      - Adjuntar el header de autorización en cada petición
      - Manejar paginación automática (limit/skip)
      - Normalizar respuestas a pd.DataFrame
      - Lanzar GuestyAPIError ante fallos HTTP o de red
    """

    def __init__(self, token: str):
        self._headers = {
            "Authorization": f"Bearer {token}",
            "accept": "application/json; charset=utf-8",
        }

    # ── Métodos privados ──────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Ejecuta un GET y retorna el JSON. Lanza GuestyAPIError ante fallos."""
        url = f"{BASE}{path}"
        try:
            resp = requests.get(url, headers=self._headers,
                                params=params, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            raise GuestyAPIError(
                f"Error HTTP {e.response.status_code} en {path}: {e.response.text[:300]}",
                status_code=e.response.status_code,
            ) from e
        except requests.exceptions.RequestException as e:
            raise GuestyAPIError(f"Error de red en {path}: {e}") from e

    def _paginate(self, path: str, params: dict | None = None,
                  results_key: str | None = None) -> list[dict]:
        """
        Itera sobre todas las páginas de un endpoint paginado con limit/skip.

        Args:
            path:        ruta del endpoint, e.g. "/listings"
            params:      parámetros extra de la query
            results_key: clave del JSON donde viven los items (auto-detecta si None)

        Returns:
            Lista con todos los registros de todas las páginas.
        """
        params = {**(params or {}), "limit": PAGE_SIZE, "skip": 0}
        all_rows: list[dict] = []

        while True:
            data = self._get(path, params)

            # Auto-detectar la clave de resultados
            if results_key:
                rows = data.get(results_key, [])
            else:
                rows = (
                    data.get("results")
                    or data.get("data")
                    or (data if isinstance(data, list) else [])
                )

            all_rows.extend(rows)

            total = data.get("total") or data.get("count") or len(all_rows)
            params["skip"] += PAGE_SIZE

            if params["skip"] >= total or not rows:
                break

        logger.debug("_paginate %s: %d registros totales", path, len(all_rows))
        return all_rows

    # ── Endpoints públicos ────────────────────────────────────────────────────

    def get_reservations_view(self, view_id: str,
                               timezone: str = "America/Bogota") -> pd.DataFrame:
        """
        Reservas filtradas por una vista guardada en Guesty.
        Endpoint: GET /v1/reservations-reports/{view_id}

        Args:
            view_id:  ID de la vista en Guesty
            timezone: zona horaria para normalizar fechas (default: Bogotá)

        Returns:
            DataFrame con los campos devueltos por la vista.
        """
        rows = self._paginate(
            f"/reservations-reports/{view_id}",
            params={"active": True, "timezone": timezone},
        )
        return pd.DataFrame(rows)

    def get_listings(self, only_active: bool = False) -> pd.DataFrame:
        """
        Todas las propiedades de la cuenta.
        Endpoint: GET /v1/listings

        Args:
            only_active: si True, filtra sólo listings activos

        Returns:
            DataFrame con los campos del listing (objetos anidados aplanados
            con pd.json_normalize, e.g. address.city → address_city).
        """
        params: dict[str, Any] = {}
        rows = self._paginate("/listings", params=params)

        if not rows:
            return pd.DataFrame()

        df = pd.json_normalize(rows)

        if only_active and "active" in df.columns:
            df = df[df["active"] == True]

        return df

    def get_reservations(
        self,
        check_in_from: str | None = None,
        check_in_to: str | None = None,
        check_out_from: str | None = None,
        check_out_to: str | None = None,
        statuses: list[str] | None = None,
        listing_id: str | None = None,
        source: str | None = None,
    ) -> pd.DataFrame:
        """
        Reservas con filtros opcionales.
        Endpoint: GET /v1/reservations

        Args:
            check_in_from:  fecha de inicio del rango de check-in (YYYY-MM-DD)
            check_in_to:    fecha de fin del rango de check-in (YYYY-MM-DD)
            check_out_from: fecha de inicio del rango de check-out (YYYY-MM-DD)
            check_out_to:   fecha de fin del rango de check-out (YYYY-MM-DD)
            statuses:       lista de estados, e.g. ["confirmed", "checked_out"]
            listing_id:     filtrar por propiedad específica
            source:         filtrar por canal (airbnb, booking, direct, etc.)

        Returns:
            DataFrame con los campos de reserva (objetos anidados aplanados).
        """
        params: dict[str, Any] = {}
        if check_in_from:  params["checkInStartDate"]  = check_in_from
        if check_in_to:    params["checkInEndDate"]    = check_in_to
        if check_out_from: params["checkOutStartDate"] = check_out_from
        if check_out_to:   params["checkOutEndDate"]   = check_out_to
        if listing_id:     params["listingId"]         = listing_id
        if source:         params["source"]            = source
        if statuses:       params["status"]            = ",".join(statuses)

        rows = self._paginate("/reservations", params=params)

        if not rows:
            return pd.DataFrame()

        return pd.json_normalize(rows)

    def get_calendar(self, listing_id: str,
                     start_date: str, end_date: str) -> pd.DataFrame:
        """
        Disponibilidad y precios de una propiedad por día.
        Endpoint: GET /v1/availability-pricing/api/calendar/listings/{id}

        Args:
            listing_id: ID de la propiedad en Guesty
            start_date: inicio del rango (YYYY-MM-DD)
            end_date:   fin del rango (YYYY-MM-DD)

        Returns:
            DataFrame con columnas: date, status, price, minNights, allotment, listing_id
        """
        data = self._get(
            f"/availability-pricing/api/calendar/listings/{listing_id}",
            params={"startDate": start_date, "endDate": end_date},
        )

        # La respuesta puede venir como {"days": [...]} o {"data": [...]}
        days = data.get("days") or data.get("data") or []

        if not days:
            return pd.DataFrame()

        df = pd.DataFrame(days)
        df["listing_id"] = listing_id
        return df

    def get_multi_calendar(self, listing_ids: list[str],
                            start_date: str, end_date: str) -> pd.DataFrame:
        """
        Disponibilidad de múltiples propiedades en un rango de fechas.
        Endpoint: GET /v1/availability-pricing/api/calendar/listings

        Args:
            listing_ids: lista de IDs de propiedades
            start_date:  inicio del rango (YYYY-MM-DD)
            end_date:    fin del rango (YYYY-MM-DD)

        Returns:
            DataFrame concatenado con calendarios de todas las propiedades.
        """
        data = self._get(
            "/availability-pricing/api/calendar/listings",
            params={
                "listingIds": ",".join(listing_ids),
                "startDate": start_date,
                "endDate": end_date,
            },
        )

        # Respuesta: lista de objetos {listingId, days: [...]}
        if isinstance(data, list):
            items = data
        else:
            items = data.get("data") or data.get("results") or []

        dfs = []
        for item in items:
            lid = item.get("listingId", item.get("_id", ""))
            days = item.get("days", [])
            if days:
                df = pd.DataFrame(days)
                df["listing_id"] = lid
                dfs.append(df)

        return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
