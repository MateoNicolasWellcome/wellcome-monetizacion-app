import importlib
from pathlib import Path
import streamlit as st
from services.client_config import (
    get_available_clients,
    get_default_client_id,
    set_active_client,
    get_active_config,
)
from services.storage import init_client_storage, migrate_legacy_data

st.set_page_config(
    page_title="Wellcome Portal",
    layout="wide",
)

BASE_DIR = Path(__file__).parent

PAGES = {
    "Monetización": "monetizacion",
    "Contabilidad": "contabilidad",
    "Plan Limpiezas": "plan_limpiezas"
}


def load_page_module(module_name: str):
    """
    Importa dinámicamente un módulo de la carpeta pages.
    Ej: "monetizacion" -> pages.monetizacion
    """
    return importlib.import_module(f"pages.{module_name}")


def main():
    # --- Selección de cliente (arriba del sidebar) ---
    clients = get_available_clients()
    client_ids = list(clients.keys())
    client_labels = list(clients.values())

    default_idx = 0
    default_id = get_default_client_id()
    if default_id in client_ids:
        default_idx = client_ids.index(default_id)

    with st.sidebar:
        st.title("Wellcome Portal")

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

        page_label = st.radio(
            "Selecciona un módulo:",
            list(PAGES.keys()),
        )

    module_name = PAGES[page_label]
    module = load_page_module(module_name)

    # Ejecutar la función principal de la página seleccionada
    if hasattr(module, "run"):
        module.run()
    else:
        st.error(f"El módulo 'pages.{module_name}' no tiene una función run().")


if __name__ == "__main__":
    main()
