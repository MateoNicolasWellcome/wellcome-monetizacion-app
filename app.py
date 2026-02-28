import importlib
from pathlib import Path
import streamlit as st

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


def main():
    # Inicializar la DB al arrancar (crea tablas si no existen)
    init_db()

    # Sidebar: selector de módulo
    st.sidebar.title("Wellcome Portal")
    st.sidebar.markdown("---")

    page_label = st.sidebar.radio(
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
