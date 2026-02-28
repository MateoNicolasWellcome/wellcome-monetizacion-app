"""
services/database.py
────────────────────
Capa de persistencia para el portal Wellcome.

Usa PostgreSQL en Railway (variable DATABASE_URL inyectada automáticamente
por el plugin de Postgres). Cae automáticamente a SQLite para desarrollo local.

Tablas gestionadas:
  - listings       → propiedades de Guesty
  - reservations   → reservas de Guesty
  - calendar_slots → disponibilidad/precio por día y propiedad
"""

import os
import logging
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import create_engine, text, Engine

logger = logging.getLogger(__name__)

# ── Singleton del engine ──────────────────────────────────────────────────────
_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL", "sqlite:///./local_dev.db")
        # Railway Postgres usa "postgres://", SQLAlchemy necesita "postgresql://"
        url = url.replace("postgres://", "postgresql://", 1)
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


@contextmanager
def _conn():
    engine = get_engine()
    with engine.connect() as conn:
        yield conn


# ── DDL — creación de tablas ──────────────────────────────────────────────────

_CREATE_LISTINGS = """
CREATE TABLE IF NOT EXISTS listings (
    id              TEXT PRIMARY KEY,
    nickname        TEXT,
    title           TEXT,
    bedrooms        INTEGER,
    bathrooms       FLOAT,
    room_type       TEXT,
    type            TEXT,
    person_capacity INTEGER,
    city            TEXT,
    street          TEXT,
    listed          BOOLEAN,
    active          BOOLEAN,
    thumbnail       TEXT,
    fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_RESERVATIONS = """
CREATE TABLE IF NOT EXISTS reservations (
    id                  TEXT PRIMARY KEY,
    confirmation_code   TEXT,
    listing_id          TEXT,
    listing_nickname    TEXT,
    check_in            DATE,
    check_out           DATE,
    nights              INTEGER,
    status              TEXT,
    source              TEXT,
    currency            TEXT,
    total_price         FLOAT,
    fare_accommodation  FLOAT,
    host_service_fee    FLOAT,
    tax                 FLOAT,
    guest_name          TEXT,
    fetched_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_CALENDAR_SLOTS = """
CREATE TABLE IF NOT EXISTS calendar_slots (
    listing_id  TEXT,
    date        DATE,
    status      TEXT,
    price       FLOAT,
    min_nights  INTEGER,
    allotment   INTEGER,
    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (listing_id, date)
)
"""


def init_db() -> None:
    """Crea todas las tablas si no existen. Llamar al inicio de la app."""
    with _conn() as conn:
        conn.execute(text(_CREATE_LISTINGS))
        conn.execute(text(_CREATE_RESERVATIONS))
        conn.execute(text(_CREATE_CALENDAR_SLOTS))
        conn.commit()
    logger.info("DB initialized (tables verified/created).")


# ── Lectura ───────────────────────────────────────────────────────────────────

def read_table(table: str, where: str | None = None,
               params: dict | None = None) -> pd.DataFrame:
    """
    Lee una tabla completa (o filtrada) como DataFrame.

    Args:
        table:  nombre de la tabla (listings | reservations | calendar_slots)
        where:  cláusula WHERE en SQL, e.g. "listing_id = :lid AND date >= :d"
        params: parámetros para la cláusula WHERE, e.g. {"lid": "abc", "d": "2025-01-01"}

    Returns:
        pd.DataFrame con las filas de la tabla.
    """
    sql = f"SELECT * FROM {table}"
    if where:
        sql += f" WHERE {where}"
    with _conn() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def is_stale(table: str, pk_col: str, pk_val: str,
             ttl_hours: float = 1.0) -> bool:
    """
    Revisa si un registro en la tabla está desactualizado (o no existe).

    Returns True si hay que refrescar desde la API, False si los datos son frescos.
    """
    sql = text(
        f"SELECT fetched_at FROM {table} WHERE {pk_col} = :val LIMIT 1"
    )
    with _conn() as conn:
        result = conn.execute(sql, {"val": pk_val}).fetchone()

    if result is None:
        return True

    fetched_at = result[0]
    if fetched_at is None:
        return True

    # Convertir a timestamp si es string (SQLite retorna strings)
    if isinstance(fetched_at, str):
        fetched_at = pd.Timestamp(fetched_at)

    age_hours = (pd.Timestamp.utcnow().replace(tzinfo=None) -
                 pd.Timestamp(fetched_at).replace(tzinfo=None)).total_seconds() / 3600
    return age_hours >= ttl_hours


# ── Escritura (upsert) ────────────────────────────────────────────────────────

_LISTINGS_COLS = [
    "id", "nickname", "title", "bedrooms", "bathrooms", "room_type",
    "type", "person_capacity", "city", "street", "listed", "active", "thumbnail",
]

_RESERVATIONS_COLS = [
    "id", "confirmation_code", "listing_id", "listing_nickname",
    "check_in", "check_out", "nights", "status", "source", "currency",
    "total_price", "fare_accommodation", "host_service_fee", "tax", "guest_name",
]

_CALENDAR_COLS = ["listing_id", "date", "status", "price", "min_nights", "allotment"]


def _fill_missing_cols(df: pd.DataFrame, required_cols: list[str]) -> pd.DataFrame:
    """Asegura que el DataFrame tenga todas las columnas requeridas (rellena con None)."""
    df = df.copy()
    for col in required_cols:
        if col not in df.columns:
            df[col] = None
    # Reemplazar NaN con None para que SQLAlchemy los envíe como NULL
    return df.where(df.notna(), other=None)


def upsert_listings(df: pd.DataFrame) -> int:
    """
    Inserta o actualiza listings en la DB.
    Columnas esperadas del DataFrame (subset de las del schema):
      id, nickname, title, bedrooms, bathrooms, room_type, type,
      person_capacity, city, street, listed, active, thumbnail
    Returns: número de filas procesadas.
    """
    if df.empty:
        return 0

    df = _fill_missing_cols(df, _LISTINGS_COLS)
    rows = df[_LISTINGS_COLS].to_dict(orient="records")
    sql = text("""
        INSERT INTO listings
            (id, nickname, title, bedrooms, bathrooms, room_type, type,
             person_capacity, city, street, listed, active, thumbnail, fetched_at)
        VALUES
            (:id, :nickname, :title, :bedrooms, :bathrooms, :room_type, :type,
             :person_capacity, :city, :street, :listed, :active, :thumbnail,
             CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO UPDATE SET
            nickname        = EXCLUDED.nickname,
            title           = EXCLUDED.title,
            bedrooms        = EXCLUDED.bedrooms,
            bathrooms       = EXCLUDED.bathrooms,
            room_type       = EXCLUDED.room_type,
            type            = EXCLUDED.type,
            person_capacity = EXCLUDED.person_capacity,
            city            = EXCLUDED.city,
            street          = EXCLUDED.street,
            listed          = EXCLUDED.listed,
            active          = EXCLUDED.active,
            thumbnail       = EXCLUDED.thumbnail,
            fetched_at      = CURRENT_TIMESTAMP
    """)

    # SQLite no soporta ON CONFLICT DO UPDATE con EXCLUDED — usar REPLACE
    engine = get_engine()
    if "sqlite" in engine.dialect.name:
        sql = text("""
            INSERT OR REPLACE INTO listings
                (id, nickname, title, bedrooms, bathrooms, room_type, type,
                 person_capacity, city, street, listed, active, thumbnail, fetched_at)
            VALUES
                (:id, :nickname, :title, :bedrooms, :bathrooms, :room_type, :type,
                 :person_capacity, :city, :street, :listed, :active, :thumbnail,
                 CURRENT_TIMESTAMP)
        """)

    with _conn() as conn:
        conn.execute(sql, rows)
        conn.commit()

    return len(rows)


def upsert_reservations(df: pd.DataFrame) -> int:
    """
    Inserta o actualiza reservas en la DB.
    Columnas esperadas: id, confirmation_code, listing_id, listing_nickname,
      check_in, check_out, nights, status, source, currency, total_price,
      fare_accommodation, host_service_fee, tax, guest_name
    Returns: número de filas procesadas.
    """
    if df.empty:
        return 0

    df = _fill_missing_cols(df, _RESERVATIONS_COLS)
    rows = df[_RESERVATIONS_COLS].to_dict(orient="records")
    engine = get_engine()

    if "sqlite" in engine.dialect.name:
        sql = text("""
            INSERT OR REPLACE INTO reservations
                (id, confirmation_code, listing_id, listing_nickname,
                 check_in, check_out, nights, status, source, currency,
                 total_price, fare_accommodation, host_service_fee, tax,
                 guest_name, fetched_at)
            VALUES
                (:id, :confirmation_code, :listing_id, :listing_nickname,
                 :check_in, :check_out, :nights, :status, :source, :currency,
                 :total_price, :fare_accommodation, :host_service_fee, :tax,
                 :guest_name, CURRENT_TIMESTAMP)
        """)
    else:
        sql = text("""
            INSERT INTO reservations
                (id, confirmation_code, listing_id, listing_nickname,
                 check_in, check_out, nights, status, source, currency,
                 total_price, fare_accommodation, host_service_fee, tax,
                 guest_name, fetched_at)
            VALUES
                (:id, :confirmation_code, :listing_id, :listing_nickname,
                 :check_in, :check_out, :nights, :status, :source, :currency,
                 :total_price, :fare_accommodation, :host_service_fee, :tax,
                 :guest_name, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                status            = EXCLUDED.status,
                total_price       = EXCLUDED.total_price,
                fare_accommodation= EXCLUDED.fare_accommodation,
                host_service_fee  = EXCLUDED.host_service_fee,
                tax               = EXCLUDED.tax,
                fetched_at        = CURRENT_TIMESTAMP
        """)

    with _conn() as conn:
        conn.execute(sql, rows)
        conn.commit()

    return len(rows)


def upsert_calendar_slots(df: pd.DataFrame) -> int:
    """
    Inserta o actualiza slots de calendario (listing_id + date como PK compuesta).
    Columnas esperadas: listing_id, date, status, price, min_nights, allotment
    Returns: número de filas procesadas.
    """
    if df.empty:
        return 0

    df = _fill_missing_cols(df, _CALENDAR_COLS)
    rows = df[_CALENDAR_COLS].to_dict(orient="records")
    engine = get_engine()

    if "sqlite" in engine.dialect.name:
        sql = text("""
            INSERT OR REPLACE INTO calendar_slots
                (listing_id, date, status, price, min_nights, allotment, fetched_at)
            VALUES
                (:listing_id, :date, :status, :price, :min_nights, :allotment,
                 CURRENT_TIMESTAMP)
        """)
    else:
        sql = text("""
            INSERT INTO calendar_slots
                (listing_id, date, status, price, min_nights, allotment, fetched_at)
            VALUES
                (:listing_id, :date, :status, :price, :min_nights, :allotment,
                 CURRENT_TIMESTAMP)
            ON CONFLICT (listing_id, date) DO UPDATE SET
                status     = EXCLUDED.status,
                price      = EXCLUDED.price,
                min_nights = EXCLUDED.min_nights,
                allotment  = EXCLUDED.allotment,
                fetched_at = CURRENT_TIMESTAMP
        """)

    with _conn() as conn:
        conn.execute(sql, rows)
        conn.commit()

    return len(rows)
