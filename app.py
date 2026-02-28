import importlib
from pathlib import Path
import streamlit as st
from services.client_config import (
    get_available_clients,
    get_default_client_id,
    set_active_client,
    get_active_config,
    authenticate_user,
    is_authenticated,
    get_authenticated_user,
    logout_user,
)
from services.storage import init_client_storage, migrate_legacy_data
from services.database import init_db

st.set_page_config(
    page_title="Wellcome Portal",
    layout="wide",
)

BASE_DIR = Path(__file__).parent

PAGES = {
    "Monetización":   "monetizacion",
    "Contabilidad":   "contabilidad",
    "Plan Limpiezas": "plan_limpiezas",
    "Propiedades":    "propiedades",
    "Calendario":     "calendario",
    "Ingresos":       "ingresos",
}


def load_page_module(module_name: str):
    """
    Importa dinámicamente un módulo de la carpeta pages.
    Ej: "monetizacion" -> pages.monetizacion
    """
    return importlib.import_module(f"pages.{module_name}")


def show_login_page():
    """Muestra la pantalla de login con campo de email."""
    st.title("Wellcome Portal")
    st.subheader("Iniciar sesión")

    with st.form("login_form"):
        email = st.text_input(
            "Correo electrónico",
            placeholder="tu@email.com",
        )
        submitted = st.form_submit_button("Ingresar")

    if submitted:
        if not email or not email.strip():
            st.error("Por favor ingresa un correo electrónico.")
            return

        user = authenticate_user(email, list(PAGES.keys()))
        if user is None:
            st.error("Acceso denegado. Este correo no está autorizado.")
        else:
            st.rerun()


def main():
    # Inicializar DB (crea tablas si no existen)
    init_db()

    # --- Gate: verificar autenticación ---
    if not is_authenticated():
        show_login_page()
        return

    user = get_authenticated_user()

    # --- Determinar clientes accesibles ---
    all_clients = get_available_clients()
    accessible_clients = {
        cid: all_clients[cid]
        for cid in user.client_ids
        if cid in all_clients
    }

    if not accessible_clients:
        st.error("No tienes acceso a ningún cliente configurado.")
        return

    # --- Determinar módulos accesibles ---
    accessible_pages = {
        label: module
        for label, module in PAGES.items()
        if label in user.modules
    }

    if not accessible_pages:
        st.error("No tienes acceso a ningún módulo.")
        return

    # --- Sidebar ---
    with st.sidebar:
        st.title("Wellcome Portal")
        st.caption(f"Sesión: {user.email}")

        if st.button("Cerrar sesión"):
            logout_user()
            st.rerun()

        st.markdown("---")

        # --- Selección de cliente ---
        client_ids = list(accessible_clients.keys())
        client_labels = list(accessible_clients.values())

        if len(client_ids) == 1:
            selected_client_id = client_ids[0]
            st.info(f"Cliente: {client_labels[0]}")
        else:
            default_idx = 0
            default_id = get_default_client_id()
            if default_id in client_ids:
                default_idx = client_ids.index(default_id)

            selected_label = st.selectbox(
                "Cliente:",
                client_labels,
                index=default_idx,
            )
            selected_client_id = client_ids[client_labels.index(selected_label)]

        set_active_client(selected_client_id)
        config = get_active_config()

        # Inicializar storage del cliente (migra datos legacy la primera vez)
        migrate_legacy_data(config.client_id)
        init_client_storage(config.client_id, config.seed_data_dir)

        st.caption(f"Operación: {config.location_title}")
        st.markdown("---")

        # --- Selección de módulo (filtrado) ---
        page_labels = list(accessible_pages.keys())

        if len(page_labels) == 1:
            page_label = page_labels[0]
            st.info(f"Módulo: {page_label}")
        else:
            page_label = st.radio(
                "Selecciona un módulo:",
                page_labels,
            )

    module_name = accessible_pages[page_label]
    module = load_page_module(module_name)

    # Ejecutar la función principal de la página seleccionada
    if hasattr(module, "run"):
        module.run()
    else:
        st.error(f"El módulo 'pages.{module_name}' no tiene una función run().")


if __name__ == "__main__":
    main()
