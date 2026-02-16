"""
Gestor de configuración multi-tenant.

Carga configuraciones de clientes desde clients_config.json y provee
la configuración del cliente activo a todos los módulos via session state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import streamlit as st

BASE_DIR = Path(__file__).parents[1]
CONFIG_FILE = BASE_DIR / "clients_config.json"


@dataclass(frozen=True)
class GuestyConfig:
    client_id_env_var: str
    client_secret_env_var: str
    view_id_checkin: str
    view_id_checkout: str
    timezone: str = "America/Bogota"


@dataclass(frozen=True)
class MonetizacionConfig:
    cuentas: list[str] = field(default_factory=lambda: ["PRINCIPAL"])
    stripe_default_start: int = 16


@dataclass(frozen=True)
class ContabilidadConfig:
    exclude_owner: Optional[str] = None
    validation_codes_minimum: frozenset[str] = field(
        default_factory=lambda: frozenset({"AF", "VATOC", "CMS"})
    )
    facturable_codes: list[str] = field(
        default_factory=lambda: ["CMS", "VATOC"]
    )
    audit_notes: str = ""
    groupings_notes: str = ""
    tolerance: float = 0.01
    max_display_rows: int = 300


@dataclass(frozen=True)
class LimpiezasConfig:
    excluded_keywords: list[str] = field(default_factory=list)
    cleaning_time_minutes: int = 40
    regular_work_hours: int = 8
    priority_window_start: int = 11
    priority_window_end: int = 15

    @property
    def priority_window_hours(self) -> int:
        return self.priority_window_end - self.priority_window_start


@dataclass(frozen=True)
class ClientConfig:
    client_id: str
    display_name: str
    app_title: str
    location_title: str
    guesty: GuestyConfig
    monetizacion: MonetizacionConfig
    contabilidad: ContabilidadConfig
    limpiezas: LimpiezasConfig
    seed_data_dir: str = "seed_data"


def _load_all_configs() -> dict:
    """Carga el archivo JSON de configuración."""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Archivo de configuración no encontrado: {CONFIG_FILE}"
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_client_config(client_id: str, raw: dict) -> ClientConfig:
    """Convierte un dict crudo en un ClientConfig tipado."""
    g = raw["guesty"]
    m = raw.get("monetizacion", {})
    c = raw.get("contabilidad", {})
    li = raw.get("limpiezas", {})

    return ClientConfig(
        client_id=client_id,
        display_name=raw["display_name"],
        app_title=raw.get("app_title", "Wellcome Portal"),
        location_title=raw.get("location_title", ""),
        guesty=GuestyConfig(
            client_id_env_var=g["client_id_env_var"],
            client_secret_env_var=g["client_secret_env_var"],
            view_id_checkin=g["view_id_checkin"],
            view_id_checkout=g["view_id_checkout"],
            timezone=g.get("timezone", "America/Bogota"),
        ),
        monetizacion=MonetizacionConfig(
            cuentas=m.get("cuentas", ["PRINCIPAL"]),
            stripe_default_start=m.get("stripe_default_start", 16),
        ),
        contabilidad=ContabilidadConfig(
            exclude_owner=c.get("exclude_owner"),
            validation_codes_minimum=frozenset(
                c.get("validation_codes_minimum", ["AF", "VATOC", "CMS"])
            ),
            facturable_codes=c.get("facturable_codes", ["CMS", "VATOC"]),
            audit_notes=c.get("audit_notes", ""),
            groupings_notes=c.get("groupings_notes", ""),
            tolerance=c.get("tolerance", 0.01),
            max_display_rows=c.get("max_display_rows", 300),
        ),
        limpiezas=LimpiezasConfig(
            excluded_keywords=li.get("excluded_keywords", []),
            cleaning_time_minutes=li.get("cleaning_time_minutes", 40),
            regular_work_hours=li.get("regular_work_hours", 8),
            priority_window_start=li.get("priority_window_start", 11),
            priority_window_end=li.get("priority_window_end", 15),
        ),
        seed_data_dir=raw.get("seed_data_dir", "seed_data"),
    )


def get_available_clients() -> dict[str, str]:
    """
    Retorna {client_id: display_name} para todos los clientes configurados.
    """
    config_data = _load_all_configs()
    return {
        cid: cdata["display_name"]
        for cid, cdata in config_data["clients"].items()
    }


def get_default_client_id() -> str:
    """Retorna el default_client del archivo de configuración."""
    config_data = _load_all_configs()
    return config_data.get("default_client", "wellcome_bogota")


def get_client_config(client_id: str) -> ClientConfig:
    """Carga y retorna el ClientConfig tipado para un client_id dado."""
    config_data = _load_all_configs()
    raw = config_data["clients"][client_id]
    return _parse_client_config(client_id, raw)


def set_active_client(client_id: str) -> None:
    """
    Almacena el client_id activo en session_state y carga su config.
    Limpia caches si el cliente cambia.
    """
    previous = st.session_state.get("active_client_id")
    if previous != client_id:
        # Limpiar claves de session_state del cliente anterior
        keys_to_clear = [
            k for k in list(st.session_state.keys())
            if k.startswith("guesty_") or k in (
                "df_full", "df_limpio", "df_malas_summary",
                "reservas_validas"
            )
        ]
        for k in keys_to_clear:
            del st.session_state[k]
        # Limpiar caches de Streamlit que dependen del cliente
        st.cache_data.clear()

    st.session_state["active_client_id"] = client_id
    st.session_state["client_config"] = get_client_config(client_id)


def get_active_config() -> ClientConfig:
    """
    Retorna el ClientConfig activo desde session state.
    Debe llamarse después de set_active_client().
    """
    config = st.session_state.get("client_config")
    if config is None:
        raise RuntimeError(
            "No hay cliente activo configurado. "
            "Llama set_active_client() primero."
        )
    return config
