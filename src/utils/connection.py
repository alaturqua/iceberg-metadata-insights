"""
This module provides functions to connect to a Trino database and perform various operations,
with caching added for performance improvements.
"""

import math
import trino
import streamlit as st
import pandas as pd
from typing import Optional
from dotenv import load_dotenv
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Connection Configuration ---
TRINO_HOST = os.getenv("TRINO_HOST", "localhost")
TRINO_PORT = int(os.getenv("TRINO_PORT", 8088))
TRINO_USER = os.getenv("TRINO_USER", "trino")
TRINO_CATALOG = os.getenv("TRINO_CATALOG", "iceberg")
TRINO_SCHEMA = os.getenv(
    "TRINO_SCHEMA", "default"
)  # Default schema, might be overridden by app selection
TRINO_HTTP_SCHEME = os.getenv("TRINO_HTTP_SCHEME", trino.constants.HTTP)

# --- Connection Management ---


# Cache the connection resource to avoid reconnecting on every script run
@st.cache_resource
def init_connection() -> Optional[trino.dbapi.Connection]:
    """Initializes a connection to Trino using Streamlit's resource caching.
    Returns:
        trino.dbapi.Connection: A connection object to interact with Trino, or None if connection fails.
    """
    try:
        conn: trino.dbapi.Connection = trino.dbapi.connect(
            host=TRINO_HOST,
            port=TRINO_PORT,
            user=TRINO_USER,
            catalog=TRINO_CATALOG,  # Connect to the main catalog initially
            schema=TRINO_SCHEMA,  # Use a default schema initially
            http_scheme=TRINO_HTTP_SCHEME,
            source="streamlit_iceberg_metadata_insights_v2",  # App identifier
        )
        logger.info(f"Successfully connected to Trino at {TRINO_HOST}:{TRINO_PORT}")
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to Trino: {e}", exc_info=True)
        st.error(f"Failed to connect to Trino: {e}")
        return None


# --- Data Fetching with Caching ---

# Cache data fetching functions to avoid redundant queries for the same table within a session duration
# The cache is keyed by the function arguments (cursor object ID isn't stable, so we might need more robust keying if cursor changes state significantly)
# Note: Using cursor directly in @st.cache_data can be tricky as its state changes.
# A safer approach might be to pass connection details or create a new cursor inside the cached function if needed,
# but for simplicity, we'll pass the active cursor, assuming its state for these read operations is consistent enough for caching.


@st.cache_data(ttl=600)  # Cache for 10 minutes
def fetch_stats(_cursor: trino.dbapi.Cursor, schema: str, table: str) -> Optional[dict]:
    """Fetches summary statistics for a given Iceberg table using cached results.
    Args:
        _cursor (trino.dbapi.Cursor): A cursor object to execute queries. (Underscore indicates it influences cache but isn't directly used if connection is stable)
        schema (str): The schema name.
        table (str): The table name.
    Returns:
        dict: A dictionary containing various statistics about the table, or None if an error occurs.
    """
    # Use a fresh cursor from the connection to ensure thread safety/state isolation if needed
    conn = init_connection()
    if not conn:
        return None
    cursor = conn.cursor()

    stats = {}
    queries = {
        # Use fully qualified names for robustness
        "Files": f'SELECT COUNT(*) FROM "{TRINO_CATALOG}"."{schema}"."{table}$files"',
        "Partitions": f'SELECT COUNT(*) FROM "{TRINO_CATALOG}"."{schema}"."{table}$partitions"',
        "Rows": f'SELECT COUNT(*) FROM "{TRINO_CATALOG}"."{schema}"."{table}"',  # Note: Count(*) on large tables can be slow
        "Snapshots": f'SELECT COUNT(*) FROM "{TRINO_CATALOG}"."{schema}"."{table}$snapshots"',
        "History": f'SELECT COUNT(*) FROM "{TRINO_CATALOG}"."{schema}"."{table}$history"',
        "Small Files (<100MB)": f'SELECT COUNT(*) FROM "{TRINO_CATALOG}"."{schema}"."{table}$files" WHERE file_size_in_bytes < 104857600',  # 100 * 1024 * 1024
        "Average File Size (MB)": f'SELECT ROUND(AVG(CAST(file_size_in_bytes AS DOUBLE))/1048576, 2) FROM "{TRINO_CATALOG}"."{schema}"."{table}$files"',  # 1024*1024
        "Largest File Size (MB)": f'SELECT ROUND(MAX(CAST(file_size_in_bytes AS DOUBLE))/1048576, 2) FROM "{TRINO_CATALOG}"."{schema}"."{table}$files"',
        "Smallest File Size (MB)": f'SELECT ROUND(MIN(CAST(file_size_in_bytes AS DOUBLE))/1048576, 2) FROM "{TRINO_CATALOG}"."{schema}"."{table}$files"',
        "Average Records per File": f'SELECT ROUND(AVG(CAST(record_count AS DOUBLE)), 0) FROM "{TRINO_CATALOG}"."{schema}"."{table}$files"',
        "Std Dev File Size (MB)": f'SELECT ROUND(STDDEV_POP(CAST(file_size_in_bytes AS DOUBLE))/1048576, 2) FROM "{TRINO_CATALOG}"."{schema}"."{table}$files"',
        "Variance File Size (Bytes²)": f'SELECT ROUND(VAR_POP(CAST(file_size_in_bytes AS DOUBLE)), 2) FROM "{TRINO_CATALOG}"."{schema}"."{table}$files"',
    }
    try:
        for key, query in queries.items():
            logger.debug(f"Executing stats query for {key}: {query}")
            result = cursor.execute(query).fetchone()
            # Handle potential None result if table is empty or metadata is missing
            stats[key] = result[0] if result and result[0] is not None else 0
        logger.info(f"Successfully fetched stats for {schema}.{table}")
        return stats
    except Exception as e:
        logger.error(f"Error fetching stats for {schema}.{table}: {e}", exc_info=True)
        st.warning(f"Could not fetch stat '{key}': {e}")
        return None  # Return None or partial dict on error? Returning None indicates overall failure.


@st.cache_data(ttl=600)
def load_snapshot_history(
    _cursor: trino.dbapi.Cursor, schema: str, table: str
) -> pd.DataFrame:
    """Loads snapshot history into a pandas DataFrame using cached results."""
    conn = init_connection()
    if not conn:
        return pd.DataFrame()
    cursor = conn.cursor()
    query = f'''
        SELECT committed_at, snapshot_id, parent_id, operation, summary
        FROM "{TRINO_CATALOG}"."{schema}"."{table}$snapshots" ORDER BY committed_at DESC
    '''
    logger.debug(f"Executing snapshot history query: {query}")
    try:
        df = pd.DataFrame(
            cursor.execute(query).fetchall(),
            columns=[
                "Committed At",
                "Snapshot ID",
                "Parent ID",
                "Operation",
                "Summary",
            ],
        )
        logger.info(f"Successfully loaded snapshot history for {schema}.{table}")
        return df
    except Exception as e:
        logger.error(
            f"Error loading snapshot history for {schema}.{table}: {e}", exc_info=True
        )
        st.error(f"Error loading snapshot history: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_file_details(
    _cursor: trino.dbapi.Cursor, schema: str, table: str
) -> pd.DataFrame:
    """Loads file details into a pandas DataFrame using cached results."""
    conn = init_connection()
    if not conn:
        return pd.DataFrame()
    cursor = conn.cursor()
    query = f'''
        SELECT content, file_format, file_path, CAST(record_count AS BIGINT) as record_count, CAST(file_size_in_bytes AS BIGINT) as file_size_in_bytes
        FROM "{TRINO_CATALOG}"."{schema}"."{table}$files" ORDER BY file_size_in_bytes DESC
    '''
    logger.debug(f"Executing file details query: {query}")
    try:
        df = pd.DataFrame(
            cursor.execute(query).fetchall(),
            columns=["Content", "Format", "Path", "Records", "Size"],
        )
        logger.info(f"Successfully loaded file details for {schema}.{table}")
        return df
    except Exception as e:
        logger.error(
            f"Error loading file details for {schema}.{table}: {e}", exc_info=True
        )
        st.error(f"Error loading file details: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_column_sizes(
    _cursor: trino.dbapi.Cursor, schema: str, table: str
) -> pd.DataFrame:
    """Loads column size information aggregated from file metadata using cached results."""
    conn = init_connection()
    if not conn:
        return pd.DataFrame()
    cursor = conn.cursor()
    # Ensure the query references the correct catalog and schema passed as arguments
    query = f"""
        SELECT
            cols.column_name,
            cols.data_type,
            SUM(col_size_in_bytes) AS col_size_in_bytes
        FROM "{TRINO_CATALOG}"."{schema}"."{table}$files" AS files
        CROSS JOIN UNNEST(column_sizes) AS col_sizes(col_id, col_size_in_bytes)
        LEFT JOIN "{TRINO_CATALOG}".information_schema.columns AS cols on
        col_sizes.col_id = cols.ordinal_position -- Assuming col_id maps directly to ordinal position; might need adjustment
        WHERE files.content = 0 -- Consider only data files
        AND cols.table_catalog = '{TRINO_CATALOG}'
        AND cols.table_schema = '{schema}'
        AND cols.table_name = '{table}'
        GROUP BY 1, 2
        ORDER BY 1
    """
    # NOTE: The join condition between $files.column_sizes.col_id and information_schema.columns
    # might be complex or depend on the connector version. The above is a guess.
    # A potentially simpler approach (if less precise for aggregate size) might query information_schema directly,
    # or rely on stats if available. Let's try a safer fallback if the complex query fails.

    try:
        logger.debug(f"Executing column sizes query (complex): {query}")
        df = pd.DataFrame(
            cursor.execute(query).fetchall(),
            columns=["Column Name", "Data Type", "Size (Bytes)"],
        )
        logger.info(f"Successfully loaded column sizes for {schema}.{table}")
        return df
    except Exception as e:
        logger.warning(
            f"Complex column size query failed for {schema}.{table}: {e}. Trying fallback.",
            exc_info=True,
        )
        # Fallback: Get column names and types from information_schema, size will be N/A
        try:
            fallback_query = f"""
                SELECT column_name, data_type, NULL AS col_size_in_bytes
                FROM "{TRINO_CATALOG}".information_schema.columns
                WHERE table_catalog = '{TRINO_CATALOG}'
                AND table_schema = '{schema}'
                AND table_name = '{table}'
                ORDER BY ordinal_position
            """
            logger.debug(f"Executing column sizes query (fallback): {fallback_query}")
            df = pd.DataFrame(
                cursor.execute(fallback_query).fetchall(),
                columns=["Column Name", "Data Type", "Size (Bytes)"],
            )
            st.info(
                "Could not calculate aggregate column sizes from file metadata; displaying column list instead."
            )
            return df
        except Exception as fallback_e:
            logger.error(
                f"Error loading column sizes (fallback) for {schema}.{table}: {fallback_e}",
                exc_info=True,
            )
            st.error(f"Error loading column information: {fallback_e}")
            return pd.DataFrame()


@st.cache_data(ttl=600)
def load_daily_growth(
    _cursor: trino.dbapi.Cursor, schema: str, table: str
) -> pd.DataFrame:
    """Loads daily growth metrics (rows, files added/deleted) from manifests using cached results."""
    conn = init_connection()
    if not conn:
        return pd.DataFrame()
    cursor = conn.cursor()
    # Query $manifests and join with $snapshots to get commit times
    query = f"""
        SELECT
            s.committed_at AS committed_at,
            SUM(m.added_rows_count) AS added_rows_count,
            SUM(m.added_data_files_count) AS added_data_files_count,
            SUM(m.deleted_rows_count) AS deleted_rows_count,
            SUM(m.deleted_data_files_count) AS deleted_data_files_count
        FROM "{TRINO_CATALOG}"."{schema}"."{table}$manifests" m
        LEFT JOIN "{TRINO_CATALOG}"."{schema}"."{table}$snapshots" s ON s.snapshot_id = m.added_snapshot_id
        GROUP BY s.committed_at -- Group by commit time to aggregate changes within a snapshot
        ORDER BY s.committed_at ASC
    """
    logger.debug(f"Executing daily growth query: {query}")
    try:
        df = pd.DataFrame(
            cursor.execute(query).fetchall(),
            columns=[
                "Committed At",
                "Added Rows Count",
                "Added Data Files Count",
                "Deleted Rows Count",
                "Deleted Data Files Count",
            ],
        )
        # Ensure numeric types
        for col in [
            "Added Rows Count",
            "Added Data Files Count",
            "Deleted Rows Count",
            "Deleted Data Files Count",
        ]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        logger.info(f"Successfully loaded daily growth data for {schema}.{table}")
        return df
    except Exception as e:
        logger.error(
            f"Error loading daily growth for {schema}.{table}: {e}", exc_info=True
        )
        st.error(f"Error loading daily growth data: {e}")
        return pd.DataFrame()


# --- Action Execution ---


def execute_alter_table(
    cursor: trino.dbapi.Cursor, schema: str, table: str, command: str
):
    """Executes an ALTER TABLE ... EXECUTE command."""
    # IMPORTANT: Add confirmation dialogs in the UI before calling this function!
    full_command = (
        f'ALTER TABLE "{TRINO_CATALOG}"."{schema}"."{table}" EXECUTE {command}'
    )
    try:
        logger.info(f"Executing ALTER TABLE command: {full_command}")
        cursor.execute(full_command)
        # Fetch results if any (some EXECUTE commands might return info)
        # results = cursor.fetchall()
        st.success(f"Successfully executed command: `{command}` on `{schema}.{table}`")
        logger.info(f"Successfully executed: {full_command}")
        # Clear relevant caches after modification
        st.cache_data.clear()  # Clear all data cache, or selectively clear specific functions if possible
        # Consider clearing resource cache too if connection state might be affected, though less likely
        # st.cache_resource.clear()
    except Exception as e:
        logger.error(
            f"Error executing ALTER TABLE command '{full_command}': {e}", exc_info=True
        )
        st.error(f"Error executing command `{command}`: {e}")


# --- Helper Functions ---


def get_schemas(cursor: trino.dbapi.Cursor) -> list[str]:
    """Gets a list of schemas in the configured catalog, excluding system schemas."""
    try:
        query = f"SELECT DISTINCT table_schema FROM {TRINO_CATALOG}.information_schema.tables WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('information_schema', 'system')"
        logger.debug(f"Executing get schemas query: {query}")
        schemas = [s[0] for s in cursor.execute(query).fetchall()]
        logger.info(f"Found schemas: {schemas}")
        return schemas
    except Exception as e:
        logger.error(f"Error fetching schemas: {e}", exc_info=True)
        st.error(f"Error fetching schemas: {e}")
        return []


def get_tables(cursor: trino.dbapi.Cursor, schema: str) -> list[str]:
    """Gets a list of tables within a specific schema."""
    try:
        # Use LOWER() for case-insensitive comparison if needed, adjust quoting if schema/catalog names have special chars
        query = f"SELECT DISTINCT table_name FROM {TRINO_CATALOG}.information_schema.tables WHERE table_type = 'BASE TABLE' AND table_schema = '{schema}'"
        logger.debug(f"Executing get tables query for schema {schema}: {query}")
        tables = [t[0] for t in cursor.execute(query).fetchall()]
        logger.info(f"Found tables in schema {schema}: {tables}")
        return tables
    except Exception as e:
        logger.error(f"Error fetching tables for schema {schema}: {e}", exc_info=True)
        st.error(f"Error fetching tables for schema {schema}: {e}")
        return []


def format_bytes(size_bytes: Optional[float]) -> str:
    """Converts bytes to a human-readable string (KB, MB, GB)."""
    if size_bytes is None or not isinstance(size_bytes, (int, float)) or size_bytes < 0:
        return "N/A"
    if size_bytes == 0:
        return "0 Bytes"
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    sizes = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    return f"{s} {sizes[i]}"
