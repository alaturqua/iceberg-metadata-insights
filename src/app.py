# Required libraries installation:
# pip install streamlit trino pandas plotly streamlit-extras

import streamlit as st
import pandas as pd
import plotly.express as px
from streamlit_extras.metric_cards import style_metric_cards
from streamlit_extras.theme import st_theme

from utils.connection import (
    init_connection,
    fetch_stats,
    load_snapshot_history,
    load_file_details,
    execute_alter_table,
)

st.set_page_config(
    page_title="Iceberg Metadata Insights", page_icon="📈", layout="wide"
)

theme = st_theme()


def main():
    st.title("📊 Iceberg Metadata Insights")
    conn = init_connection()
    cursor = conn.cursor()

    with st.sidebar:
        st.header("🔍 Select Table")
        schemas = [
            s[0]
            for s in cursor.execute(
                "select distinct table_schema from iceberg.information_schema.tables where table_type = 'BASE TABLE' and table_schema not in ('information_schema', 'system')"
            )
        ]
        schema = st.selectbox("Schema", schemas)

        tables = [
            t[0]
            for t in cursor.execute(
                f"select distinct table_name from iceberg.information_schema.tables where table_type = 'BASE TABLE' and table_schema not in ('information_schema', 'system') and lower(table_schema) = lower('{schema}')"
            )
        ]
        table = st.selectbox("Table", tables)

        st.divider()
        st.header("⚙️ Table Actions")
        if st.button("📈 Analyze Table", use_container_width=True):
            with st.spinner("Analyzing table..."):
                cursor.execute(f"ANALYZE {schema}.{table}").fetchall()
                st.success("Table analyzed successfully.")

        if st.button("🔧 Optimize/Vacuum Table", use_container_width=True):
            with st.spinner("Optimizing table..."):
                execute_alter_table(
                    cursor, schema, table, "optimize(file_size_threshold => '128MB')"
                )

        if st.button("📑 Optimize Manifests", use_container_width=True):
            with st.spinner("Optimizing manifests..."):
                execute_alter_table(cursor, schema, table, "optimize_manifests")

        if st.button("⏳ Expire Snapshots", use_container_width=True):
            with st.spinner("Expiring snapshots..."):
                execute_alter_table(
                    cursor,
                    schema,
                    table,
                    "expire_snapshots(retention_threshold => '7d')",
                )

        if st.button("🗑️ Remove Orphan Files", use_container_width=True):
            with st.spinner("Removing orphan files..."):
                execute_alter_table(
                    cursor,
                    schema,
                    table,
                    "remove_orphan_files(retention_threshold => '7d')",
                )

        if st.button("❌ Drop Extended Stats", use_container_width=True):
            with st.spinner("Dropping extended stats..."):
                execute_alter_table(cursor, schema, table, "drop_extended_stats")

    if table:
        st.header(f"📋 {schema}.{table}")
        stats = fetch_stats(cursor, schema, table)

        st.subheader("📌 Table Overview")
        row1 = st.columns(6)
        row1[0].metric("Files", f"{stats['Files']:,}")
        row1[1].metric("Partitions", f"{stats['Partitions']:,}")
        row1[2].metric("Rows", f"{stats['Rows']:,}")
        row1[3].metric("Snapshots", f"{stats['Snapshots']:,}")
        row1[4].metric("History", f"{stats['History']:,}")
        row1[5].metric("Small Files (<100MB)", f"{stats['Small Files (<100MB)']:,}")

        st.subheader("📏 File Size Metrics")
        row2 = st.columns(6)
        row2[0].metric("Avg File Size (MB)", f"{stats['Average File Size (MB)']:.2f}")
        row2[1].metric(
            "Largest File Size (MB)", f"{stats['Largest File Size (MB)']:.2f}"
        )
        row2[2].metric(
            "Smallest File Size (MB)", f"{stats['Smallest File Size (MB)']:.2f}"
        )
        row2[3].metric("Avg Records per File", f"{stats['Average Records per File']:,}")
        row2[4].metric(
            "Std Dev File Size (MB)", f"{stats['Std Dev File Size (MB)']:.2f}"
        )
        row2[5].metric(
            "Variance File Size (Bytes²)", f"{stats['Variance File Size (Bytes²)']:,}"
        )

        if theme.get("base") == "dark":
            style_metric_cards(
                background_color="#1B1C24",
                border_color="#292D34",
            )
        else:
            style_metric_cards()

        snapshot_history = load_snapshot_history(cursor, schema, table)
        st.subheader("⏳ Snapshot Timeline")
        if not snapshot_history.empty:
            fig_snapshots = px.scatter(
                snapshot_history,
                x="Committed At",
                y="Operation",
                color="Operation",
                hover_data=["Snapshot ID", "Parent ID", "Summary"],
                title="Snapshot Timeline",
            )
            st.plotly_chart(fig_snapshots, use_container_width=True)
            with st.expander("Snapshot Details"):
                st.dataframe(snapshot_history)
        else:
            st.info("No snapshot history available.")

        file_details = load_file_details(cursor, schema, table)
        st.subheader("📂 File Size Distribution")
        if not file_details.empty:
            fig_size = px.histogram(
                file_details, x="Size", title="File Size Distribution (bytes)", nbins=50
            )
            st.plotly_chart(fig_size, use_container_width=True)
            with st.expander("Detailed File Information"):
                st.dataframe(file_details)
        else:
            st.info("No file details available.")

        # Metadata section
        st.subheader("📋 Table Metadata")
        tabs = st.tabs(
            [
                "🔠 Show DDL",
                "🧾 Properties",
                "📜 History",
                "🧩 Manifests (Current)",
                "🧩 Manifests (All)",
                "🧾 Metadata Log",
                "📸 Snapshots",
                "📂 Partitions",
                "📁 Files",
                "🧾 Entries (Current)",
                "📚 Entries (All)",
                "🔖 References",
            ]
        )

        with tabs[0]:
            try:
                ddl = cursor.execute(f"show create table {schema}.{table}").fetchall()[
                    0
                ][0]
                st.code(ddl, language="sql")
            except Exception as e:
                st.error(f"Error loading references: {str(e)}")

        with tabs[1]:
            try:
                props_df = pd.DataFrame(
                    cursor.execute(
                        f'SELECT * FROM {schema}."{table}$properties"'
                    ).fetchall(),
                    columns=["Key", "Value"],
                )
                st.dataframe(props_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading properties: {str(e)}")

        with tabs[2]:
            try:
                history_df = pd.DataFrame(
                    cursor.execute(
                        f'SELECT * FROM {schema}."{table}$history"'
                    ).fetchall(),
                    columns=[
                        "Made Current At",
                        "Snapshot ID",
                        "Parent ID",
                        "Is Current Ancestor",
                    ],
                )
                st.dataframe(history_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading history: {str(e)}")

        with tabs[3]:
            try:
                manifests_df = pd.DataFrame(
                    cursor.execute(
                        f'SELECT * FROM {schema}."{table}$manifests"'
                    ).fetchall(),
                    columns=[
                        "Path",
                        "Length",
                        "Partition Spec ID",
                        "Added Snapshot ID",
                        "Added Data Files Count",
                        "Existing Data Files Count",
                        "Deleted Data Files Count",
                        "Added Position Deletes Count",
                        "Existing Position Deletes Count",
                        "Deleted Position Deletes Count",
                        "Partitions",
                    ],
                )
                st.dataframe(manifests_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading manifests: {str(e)}")
        with tabs[4]:
            try:
                all_manifests_df = pd.DataFrame(
                    cursor.execute(
                        f'SELECT * FROM {schema}."{table}$all_manifests"'
                    ).fetchall(),
                    columns=[
                        "Path",
                        "Length",
                        "Partition Spec ID",
                        "Added Snapshot ID",
                        "Added Data Files Count",
                        "Existing Data Files Count",
                        "Deleted Data Files Count",
                        "Partition Summaries",
                    ],
                )
                st.dataframe(all_manifests_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading all manifests: {str(e)}")
        with tabs[5]:
            try:
                meta_log_df = pd.DataFrame(
                    cursor.execute(
                        f'SELECT * FROM {schema}."{table}$metadata_log_entries"'
                    ).fetchall(),
                    columns=[
                        "Timestamp",
                        "File",
                        "Latest Snapshot ID",
                        "Latest Schema ID",
                        "Latest Sequence Number",
                    ],
                )
                st.dataframe(meta_log_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading metadata log: {str(e)}")
        with tabs[6]:
            try:
                snapshots_df = pd.DataFrame(
                    cursor.execute(
                        f'SELECT * FROM {schema}."{table}$snapshots"'
                    ).fetchall(),
                    columns=[
                        "Committed At",
                        "Snapshot ID",
                        "Parent ID",
                        "Operation",
                        "Manifest List",
                        "Summary",
                    ],
                )
                st.dataframe(snapshots_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading snapshots: {str(e)}")

        with tabs[7]:
            try:
                partitions_df = pd.DataFrame(
                    cursor.execute(
                        f'SELECT * FROM {schema}."{table}$partitions"'
                    ).fetchall(),
                    columns=[
                        "Record Count",
                        "File Count",
                        "Total Size",
                        "Data",
                    ],
                )
                st.dataframe(partitions_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading partitions: {str(e)}")
        with tabs[8]:
            try:
                files_df = pd.DataFrame(
                    cursor.execute(f'''
                        SELECT content, file_path, record_count, file_format, file_size_in_bytes
                        FROM {schema}."{table}$files"
                    ''').fetchall(),
                    columns=[
                        "Content",
                        "File Path",
                        "Record Count",
                        "File Format",
                        "File Size (Bytes)",
                    ],
                )
                st.dataframe(files_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading files: {str(e)}")
        with tabs[9]:
            try:
                entries_df = pd.DataFrame(
                    cursor.execute(
                        f'SELECT status, snapshot_id, sequence_number, file_sequence_number, data_file, readable_metrics FROM {schema}."{table}$entries"'
                    ).fetchall(),
                    columns=[
                        "Status",
                        "Snapshot ID",
                        "Seq Num",
                        "File Seq Num",
                        "Data File",
                        "Readable Metrics",
                    ],
                )
                st.dataframe(entries_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading entries: {str(e)}")
        with tabs[10]:
            try:
                all_entries_df = pd.DataFrame(
                    cursor.execute(
                        f'SELECT status, snapshot_id, sequence_number, file_sequence_number, data_file, readable_metrics FROM {schema}."{table}$all_entries"'
                    ).fetchall(),
                    columns=[
                        "Status",
                        "Snapshot ID",
                        "Seq Num",
                        "File Seq Num",
                        "Data File",
                        "Readable Metrics",
                    ],
                )
                st.dataframe(all_entries_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading all entries: {str(e)}")
        with tabs[11]:
            try:
                refs_df = pd.DataFrame(
                    cursor.execute(f'SELECT * FROM {schema}."{table}$refs"').fetchall(),
                    columns=[
                        "Name",
                        "Type",
                        "Snapshot ID",
                        "Max Reference Age (ms)",
                        "Min Snapshots to Keep",
                        "Max Snapshot Age (ms)",
                    ],
                )
                st.dataframe(refs_df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading references: {str(e)}")


if __name__ == "__main__":
    main()
