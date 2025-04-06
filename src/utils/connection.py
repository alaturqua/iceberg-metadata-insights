"""
This module provides functions to connect to a Trino database and perform various operations.
"""

import trino
import streamlit as st
import pandas as pd
from typing import Optional
from dotenv import load_dotenv
import os

load_dotenv()

TRINO_HOST = os.getenv("TRINO_HOST", "localhost")
TRINO_PORT = int(os.getenv("TRINO_PORT", 8088))
TRINO_USER = os.getenv("TRINO_USER", "trino")
TRINO_CATALOG = os.getenv("TRINO_CATALOG", "iceberg")
TRINO_SCHEMA = os.getenv("TRINO_SCHEMA", "default")
TRINO_HTTP_SCHEME = os.getenv("TRINO_HTTP_SCHEME", trino.constants.HTTP)


def init_connection() -> Optional[trino.dbapi.Connection]:
    """Initializes a connection to Trino.
    Returns:
        trino.dbapi.Connection: A connection object to interact with Trino.
    """

    try:
        conn: trino.dbapi.Connection = trino.dbapi.connect(
            host=TRINO_HOST,
            port=TRINO_PORT,
            user=TRINO_USER,
            catalog=TRINO_CATALOG,
            schema=TRINO_SCHEMA,
            http_scheme=TRINO_HTTP_SCHEME,
            source="streamlit_iceberg_metadata_insights",
        )
        return conn
    except Exception as e:
        st.error(f"Failed to connect to Trino: {e}")
        return None


def fetch_stats(cursor: trino.dbapi.Cursor, schema: str, table: str) -> dict:
    """Fetches statistics from a Trino table.
    Args:
        cursor (trino.dbapi.Cursor): A cursor object to execute queries.
        schema (str): The schema name.
        table (str): The table name.
    Returns:
        dict: A dictionary containing various statistics about the table.
    """
    queries = {
        "Files": f'SELECT COUNT(*) FROM {schema}."{table}$files"',
        "Partitions": f'SELECT COUNT(*) FROM {schema}."{table}$partitions"',
        "Rows": f'SELECT COUNT(*) FROM {schema}."{table}"',
        "Snapshots": f'SELECT COUNT(*) FROM {schema}."{table}$snapshots"',
        "History": f'SELECT COUNT(*) FROM {schema}."{table}$history"',
        "Small Files (<100MB)": f'SELECT COUNT(*) FROM {schema}."{table}$files" WHERE file_size_in_bytes < 104857600',
        "Average File Size (MB)": f'SELECT ROUND(AVG(file_size_in_bytes)/1000000, 2) FROM {schema}."{table}$files"',
        "Largest File Size (MB)": f'SELECT ROUND(MAX(file_size_in_bytes)/1000000, 2) FROM {schema}."{table}$files"',
        "Smallest File Size (MB)": f'SELECT ROUND(MIN(file_size_in_bytes)/1000000, 2) FROM {schema}."{table}$files"',
        "Average Records per File": f'SELECT ROUND(AVG(record_count), 0) FROM {schema}."{table}$files"',
        "Std Dev File Size (MB)": f'SELECT ROUND(STDDEV_POP(file_size_in_bytes)/1000000, 2) FROM {schema}."{table}$files"',
        "Variance File Size (Bytes²)": f'SELECT ROUND(VAR_POP(file_size_in_bytes), 2) FROM {schema}."{table}$files"',
    }
    return {key: cursor.execute(query).fetchone()[0] for key, query in queries.items()}


def load_snapshot_history(cursor, schema, table):
    return pd.DataFrame(
        cursor.execute(f'''
        SELECT committed_at, snapshot_id, parent_id, operation, summary
        FROM {schema}."{table}$snapshots" ORDER BY committed_at DESC
    ''').fetchall(),
        columns=["Committed At", "Snapshot ID", "Parent ID", "Operation", "Summary"],
    )


def load_file_details(cursor, schema, table):
    return pd.DataFrame(
        cursor.execute(f'''
        SELECT content, file_format, file_path, CAST(record_count AS bigint), CAST(file_size_in_bytes AS bigint)
        FROM {schema}."{table}$files" ORDER BY file_size_in_bytes DESC
    ''').fetchall(),
        columns=["Content", "Format", "Path", "Records", "Size"],
    )


def load_column_sizes(cursor, schema, table):
    return pd.DataFrame(
        cursor.execute(f"""
        select 
        cols.column_name,
        cols.data_type,
        sum(col_size_in_bytes) as col_size_in_bytes
        from iceberg.gold."orders$files" as files
        cross join unnest(column_sizes) as col_sizes(col_id, col_size_in_bytes)
        left join iceberg.information_schema.columns as cols on col_sizes.col_id = cols.ordinal_position
        where files.content = 0
        and cols.table_catalog = 'iceberg'
        and cols.table_schema = '{schema}'
        and cols.table_name = '{table}'
        group by 1, 2
        order by 1
    """).fetchall(),
        columns=["Column Name", "Data Type", "Size (Bytes)"],
    )


def load_daily_growth(cursor, schema, table):
    return pd.DataFrame(
        cursor.execute(f"""
        SELECT
        s.committed_at as committed_at,
        added_rows_count as added_rows_count,
        added_data_files_count as added_data_files_count,
        deleted_rows_count as deleted_rows_count,
        deleted_data_files_count as deleted_data_files_count
        from {schema}."{table}$manifests" m
        left join {schema}."{table}$snapshots" s on s.snapshot_id=m.added_snapshot_id
    """).fetchall(),
        columns=[
            "Committed At",
            "Added Rows Count",
            "Added Data Files Count",
            "Deleted Rows Count",
            "Deleted Data Files Count",
        ],
    )


def execute_alter_table(cursor, schema, table, command):
    cursor.execute(f"ALTER TABLE {schema}.{table} EXECUTE {command}")
    st.success(f"Executed command: {command}")
