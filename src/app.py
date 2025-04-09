import logging

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_extras.metric_cards import style_metric_cards
from streamlit_extras.theme import st_theme

from utils.connection import (
    execute_alter_table,
    fetch_stats,
    get_schemas,
    get_tables,
    init_connection,
    load_column_sizes,
    load_daily_growth,
    load_file_details,
    load_snapshot_history,
)
from utils.helper import display_dataframe, format_bytes, safe_float

# --- Page Configuration ---
st.set_page_config(
    page_title="Iceberg Metadata Insights",
    page_icon="🧊",  # Using an Iceberg emoji
    layout="wide",
)

theme = st_theme()

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Main Application Logic ---
def main():
    st.title("🧊 Iceberg Metadata Insights")

    # Initialize connection
    conn = init_connection()
    if not conn:
        st.error(
            "Database connection failed. Please check configuration and ensure Trino is running."
        )
        st.stop()  # Stop execution if connection fails

    cursor = conn.cursor()

    # --- Sidebar for Selection and Actions ---
    with st.sidebar:
        st.header("📍 Select Table")

        # Fetch schemas only once and cache them
        @st.cache_data
        def cached_get_schemas():
            return get_schemas(cursor)

        schemas = cached_get_schemas()
        if not schemas:
            st.warning("No schemas found or error fetching schemas.")
            st.stop()

        # Initialize session state for schema, table and query execution flag
        if "selected_schema" not in st.session_state:
            st.session_state.selected_schema = schemas[0] if schemas else None
        if "selected_table" not in st.session_state:
            st.session_state.selected_table = None
        if "execute_queries" not in st.session_state:
            st.session_state.execute_queries = False

        # Schema selection
        selected_schema = st.selectbox(
            "Schema",
            schemas,
            index=(
                schemas.index(st.session_state.selected_schema)
                if st.session_state.selected_schema in schemas
                else 0
            ),
            key="schema_select",
        )

        # Update session state if schema changes
        if selected_schema != st.session_state.selected_schema:
            st.session_state.selected_schema = selected_schema
            st.session_state.selected_table = (
                None  # Reset table selection when schema changes
            )
            st.session_state.execute_queries = False  # Reset query execution flag

        # Fetch tables based on selected schema
        @st.cache_data
        def cached_get_tables(schema):
            return get_tables(cursor, schema)

        tables = cached_get_tables(st.session_state.selected_schema)
        if not tables:
            st.warning(
                f"No tables found in schema '{st.session_state.selected_schema}' or error fetching tables."
            )
            st.session_state.selected_table = None
            st.session_state.execute_queries = False
        else:
            # Define a callback for table selection
            def on_table_select():
                st.session_state.execute_queries = True

            selected_table = st.selectbox(
                "Table",
                tables,
                index=(
                    tables.index(st.session_state.selected_table)
                    if st.session_state.selected_table in tables
                    else 0
                ),
                key="table_select",
                on_change=on_table_select,
            )

            st.session_state.selected_table = selected_table

            # Add an explicit analyze button if preferred
            if not st.session_state.execute_queries and st.session_state.selected_table:
                if st.button(
                    "Load Table Details", type="primary", use_container_width=True
                ):
                    st.session_state.execute_queries = True
                    st.rerun()

        st.divider()

        # --- Table Actions ---
        if st.session_state.selected_table and st.session_state.execute_queries:
            st.header("⚙️ Table Actions")
            st.warning("Actions modify table state. Use with caution!")

            # Analyze Table
            if st.button(
                "📊 Analyze Table (Compute Stats)",
                use_container_width=True,
                help="Updates table and column statistics.",
            ):
                with st.spinner("Executing ANALYZE..."):
                    try:
                        analyze_query = f'ANALYZE "{st.session_state.selected_schema}"."{st.session_state.selected_table}"'
                        logger.info(f"Executing: {analyze_query}")
                        cursor.execute(analyze_query).fetchall()
                        st.success("ANALYZE command executed successfully.")
                        st.cache_data.clear()
                    except Exception as e:
                        logger.error(f"Error executing ANALYZE: {e}", exc_info=True)
                        st.error(f"Error executing ANALYZE: {e}")

            # Optimize/Vacuum
            optimize_threshold = st.text_input(
                "Optimize File Size Threshold (e.g., 128MB)",
                "128MB",
                help="Files smaller than this may be compacted. Format: number followed by KB, MB, GB.",
            )
            if st.button(
                "🔧 Optimize/Compact Files",
                use_container_width=True,
                help="Rewrites small files into larger ones based on threshold.",
            ):
                with st.spinner(
                    f"Optimizing table with threshold {optimize_threshold}..."
                ):
                    execute_alter_table(
                        cursor,
                        selected_schema,
                        selected_table,
                        f"optimize(file_size_threshold => '{optimize_threshold}')",
                    )

            # Optimize Manifests
            if st.button(
                "📑 Optimize Manifests",
                use_container_width=True,
                help="Compacts metadata manifest files.",
            ):
                with st.spinner("Optimizing manifests..."):
                    execute_alter_table(
                        cursor,
                        selected_schema,
                        selected_table,
                        "optimize_manifests",
                    )

            # Expire Snapshots
            expire_retention = st.text_input(
                "Expire Snapshots Older Than",
                "7d",
                help="e.g., '7d', '1h'. Snapshots older than this threshold will be expired.",
            )
            if st.button(
                "⏳ Expire Snapshots",
                use_container_width=True,
                help="Removes old snapshot metadata according to retention.",
            ):
                with st.spinner("Expiring snapshots..."):
                    execute_alter_table(
                        cursor,
                        selected_schema,
                        selected_table,
                        f"expire_snapshots(retention_threshold => '{expire_retention}')",
                    )

            # Remove Orphan Files
            orphan_retention = st.text_input(
                "Remove Orphan Files Older Than",
                "7d",
                help="e.g., '7d', '1h'. Files not referenced by metadata older than this will be removed.",
            )
            if st.button(
                "🗑️ Remove Orphan Files",
                use_container_width=True,
                help="Deletes data files no longer referenced by valid snapshots.",
            ):
                with st.spinner("Removing orphan files..."):
                    execute_alter_table(
                        cursor,
                        selected_schema,
                        selected_table,
                        f"remove_orphan_files(retention_threshold => '{orphan_retention}')",
                    )

            # Drop Extended Stats (Less common action)
            if st.button(
                "❌ Drop Extended Stats",
                use_container_width=True,
                type="secondary",
                help="Removes extended statistics like histograms (if collected).",
            ):
                with st.spinner("Dropping extended stats..."):
                    execute_alter_table(
                        cursor,
                        selected_schema,
                        selected_table,
                        "drop_extended_stats",
                    )
        else:
            st.sidebar.info("Select a table to view details and actions.")

    # --- Main Content Area ---
    if selected_table and selected_schema:
        st.header(f"Inspecting: `{selected_schema}`.`{selected_table}`")

        if not st.session_state.execute_queries:
            st.info("Select a table and click 'Load Table Details' to view analytics.")
            st.stop()  # Stop execution until user explicitly loads data

        # From this point on, all your existing query-dependent code executes
        # only when execute_queries is True

        # Fetch and display summary stats
        stats = fetch_stats(cursor, selected_schema, selected_table)

        if stats:
            st.subheader("📌 Table Overview")
            # Use safe_float and format_bytes for robust display
            row1_cols = st.columns(6)
            row1_cols[0].metric("Files", f"{int(safe_float(stats.get('Files', 0))):,}")
            row1_cols[1].metric(
                "Partitions", f"{int(safe_float(stats.get('Partitions', 0))):,}"
            )
            row1_cols[2].metric("Rows", f"{int(safe_float(stats.get('Rows', 0))):,}")
            row1_cols[3].metric(
                "Snapshots", f"{int(safe_float(stats.get('Snapshots', 0))):,}"
            )
            row1_cols[4].metric(
                "History Entries", f"{int(safe_float(stats.get('History', 0))):,}"
            )
            row1_cols[5].metric(
                "Small Files (<100MB)",
                f"{int(safe_float(stats.get('Small Files (<100MB)', 0))):,}",
            )

            st.subheader("📏 File Size Metrics")
            row2_cols = st.columns(6)
            row2_cols[0].metric(
                "Avg File Size",
                format_bytes(
                    safe_float(stats.get("Average File Size (MB)", 0)) * 1024 * 1024
                ),
            )  # Convert MB back to Bytes for formatter
            row2_cols[1].metric(
                "Largest File",
                format_bytes(
                    safe_float(stats.get("Largest File Size (MB)", 0)) * 1024 * 1024
                ),
            )
            row2_cols[2].metric(
                "Smallest File",
                format_bytes(
                    safe_float(stats.get("Smallest File Size (MB)", 0)) * 1024 * 1024
                ),
            )
            row2_cols[3].metric(
                "Avg Records/File",
                f"{int(safe_float(stats.get('Average Records per File', 0))):,}",
            )
            row2_cols[4].metric(
                "Std Dev File Size",
                format_bytes(
                    safe_float(stats.get("Std Dev File Size (MB)", 0)) * 1024 * 1024
                ),
            )
            if theme.get("base") == "dark":
                style_metric_cards(
                    background_color="#1B1C24",
                    border_color="#292D34",
                )
            else:
                style_metric_cards()

        else:
            st.warning("Could not fetch summary statistics for the table.")

        st.divider()

        # --- Charts Section ---
        st.subheader("📈 Charts & Trends")
        chart_tabs = st.tabs(
            [
                "Snapshot Timeline",
                "Data Growth (Rows)",
                "Data Growth (Files)",
                "File Size Distribution",
                "Column Sizes",
            ]
        )

        with chart_tabs[0]:
            st.markdown("#### 📸 Snapshot Timeline")
            snapshot_history_df = load_snapshot_history(
                cursor, selected_schema, selected_table
            )
            if not snapshot_history_df.empty:
                # Ensure datetime conversion for plotting
                snapshot_history_df["Committed At"] = pd.to_datetime(
                    snapshot_history_df["Committed At"], errors="coerce"
                )
                fig_snapshots = px.scatter(
                    snapshot_history_df.dropna(
                        subset=["Committed At"]
                    ),  # Drop rows where conversion failed
                    x="Committed At",
                    # Use 'Snapshot ID' or index if y doesn't make sense
                    y=snapshot_history_df.index,  # Plot against index to show sequence
                    color="Operation",
                    hover_data=["Snapshot ID", "Parent ID", "Operation", "Summary"],
                    title="Snapshot Timeline by Operation",
                    labels={"y": "Snapshot Sequence Index"},
                )
                fig_snapshots.update_layout(
                    xaxis_title="Commit Time", yaxis_title="Snapshot Sequence Index"
                )
                st.plotly_chart(fig_snapshots, use_container_width=True)
            else:
                st.info("No snapshot history available to plot.")

        with chart_tabs[1]:
            st.markdown("#### 📈 Data Growth (Rows)")
            daily_growth_df = load_daily_growth(cursor, selected_schema, selected_table)
            if not daily_growth_df.empty:
                daily_growth_df["Committed At"] = pd.to_datetime(
                    daily_growth_df["Committed At"], errors="coerce"
                )
                # Plot added vs deleted rows over time
                fig_growth_rows = px.line(
                    daily_growth_df.dropna(subset=["Committed At"]),
                    x="Committed At",
                    y=["Added Rows Count", "Deleted Rows Count"],
                    title="Added vs Deleted Rows per Snapshot",
                    labels={"value": "Row Count", "variable": "Action"},
                    markers=True,
                )
                fig_growth_rows.update_layout(
                    xaxis_title="Commit Time", yaxis_title="Number of Rows"
                )
                st.plotly_chart(fig_growth_rows, use_container_width=True)
            else:
                st.info("No daily growth data available to plot.")

        with chart_tabs[2]:
            st.markdown("#### 📈 Data Growth (Files)")
            # Use the same daily_growth_df loaded previously
            if not daily_growth_df.empty:
                # Plot added vs deleted files over time
                fig_growth_files = px.line(
                    daily_growth_df.dropna(subset=["Committed At"]),
                    x="Committed At",
                    y=["Added Data Files Count", "Deleted Data Files Count"],
                    title="Added vs Deleted Data Files per Snapshot",
                    labels={"value": "File Count", "variable": "Action"},
                    markers=True,
                )
                fig_growth_files.update_layout(
                    xaxis_title="Commit Time", yaxis_title="Number of Data Files"
                )
                st.plotly_chart(fig_growth_files, use_container_width=True)
            else:
                st.info(
                    "No daily growth data available to plot."
                )  # Should be covered by previous check

        with chart_tabs[3]:
            st.markdown("#### 📂 File Size Distribution")
            file_details_df = load_file_details(cursor, selected_schema, selected_table)
            if not file_details_df.empty:
                # Convert size to MB for histogram readability
                file_details_df["Size (MB)"] = safe_float(file_details_df["Size"]) / (
                    1024 * 1024
                )

                # Create size categories for better visualization
                bins = [0, 1, 10, 50, 100, 500, float("inf")]
                labels = [
                    "<1MB",
                    "1-10MB",
                    "10-50MB",
                    "50-100MB",
                    "100-500MB",
                    ">500MB",
                ]
                file_details_df["Size Category"] = pd.cut(
                    file_details_df["Size (MB)"], bins=bins, labels=labels
                )

                # Count files by size category
                size_counts = (
                    file_details_df["Size Category"].value_counts().sort_index()
                )

                # Create bar chart
                fig_size_dist = px.bar(
                    x=size_counts.index,
                    y=size_counts.values,
                    title="File Size Distribution by Category",
                    labels={"x": "File Size Category", "y": "Number of Files"},
                )
                st.plotly_chart(fig_size_dist, use_container_width=True)

                # Show detailed stats
                with st.expander("Show detailed statistics"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Total files", len(file_details_df))
                        st.metric(
                            "Average file size",
                            f"{file_details_df['Size (MB)'].mean():.2f} MB",
                        )
                        st.metric(
                            "Median file size",
                            f"{file_details_df['Size (MB)'].median():.2f} MB",
                        )
                    with col2:
                        st.metric(
                            "Min file size",
                            f"{file_details_df['Size (MB)'].min():.2f} MB",
                        )
                        st.metric(
                            "Max file size",
                            f"{file_details_df['Size (MB)'].max():.2f} MB",
                        )
                        st.metric(
                            "Std dev", f"{file_details_df['Size (MB)'].std():.2f} MB"
                        )
            else:
                st.info("No file details available to plot distribution.")

        with chart_tabs[4]:
            st.markdown("#### 📊 Column Sizes")
            column_sizes_df = load_column_sizes(cursor, selected_schema, selected_table)
            if (
                not column_sizes_df.empty
                and "Size (Bytes)" in column_sizes_df.columns
                and column_sizes_df["Size (Bytes)"].notna().any()
            ):
                # Plot if size data is available and not all null
                column_sizes_df["Size (MB)"] = pd.to_numeric(
                    column_sizes_df["Size (Bytes)"], errors="coerce"
                ).fillna(0) / (1024 * 1024)
                fig_col_sizes = px.bar(
                    column_sizes_df,
                    x="Column Name",
                    y="Size (MB)",
                    color="Data Type",
                    title="Estimated Aggregate Column Sizes",
                    labels={"Size (MB)": "Total Size (MB)"},
                    # text="Size (MB)" # Adding text might clutter the bar chart
                )
                # fig_col_sizes.update_traces(texttemplate='%{text:.2s} MB', textposition='outside') # Formatting text
                fig_col_sizes.update_layout(
                    xaxis_title="Column Name", yaxis_title="Estimated Size (MB)"
                )
                st.plotly_chart(fig_col_sizes, use_container_width=True)
            elif not column_sizes_df.empty:
                st.info(
                    "Aggregate column size data could not be calculated from file metadata. Displaying column list instead."
                )
                st.dataframe(
                    column_sizes_df[["Column Name", "Data Type"]],
                    use_container_width=True,
                )
            else:
                st.info("No column size information available.")

        st.divider()

        # --- Metadata Tables Section ---
        st.subheader("📋 Detailed Metadata Tables")
        # Define all metadata tables
        metadata_tables = {
            "$properties": {
                "cols": ["Key", "Value"],
                "desc": "Table configuration properties.",
            },
            "$history": {
                "cols": [
                    "Made Current At",
                    "Snapshot ID",
                    "Parent ID",
                    "Is Current Ancestor",
                ],
                "desc": "Log of metadata changes (snapshot commits).",
            },
            "$metadata_log_entries": {
                "cols": [
                    "Timestamp",
                    "File",
                    "Latest Snapshot ID",
                    "Latest Schema ID",
                    "Latest Sequence Number",
                ],
                "desc": "Log of metadata file updates.",
            },
            "$snapshots": {
                "cols": [
                    "Committed At",
                    "Snapshot ID",
                    "Parent ID",
                    "Operation",
                    "Manifest List",
                    "Summary",
                ],
                "desc": "Detailed view of table snapshots.",
            },
            "$manifests": {
                "cols": [
                    "Path",
                    "Length",
                    "Partition Spec ID",
                    "Added Snapshot ID",
                    "Added Data Files Count",
                    "Added Rows Count",
                    "Existing Data Files Count",
                    "Existing Rows Count",
                    "Deleted Data Files Count",
                    "Deleted Rows Count",
                ],
                "desc": "Manifest files for the current snapshot.",
            },
            "$all_manifests": {
                "cols": [
                    "Path",
                    "Length",
                    "Partition Spec ID",
                    "Added Snapshot ID",
                    "Added Data Files Count",
                    "Existing Data Files Count",
                    "Deleted Data Files Count",
                ],
                "desc": "Manifest files for all snapshots.",
            },
            "$partitions": {
                "cols": [
                    "Partition",
                    "Record Count",
                    "File Count",
                    "Total Size",
                    "Data",
                ],
                "desc": "Detailed view of table partitions.",
            },
            "$files": {
                "cols": [
                    "Content",
                    "File Path",
                    "File Format",
                    "Partition",
                    "Record Count",
                    "File Size (Bytes)",
                    "Column Sizes",
                    "Value Counts",
                    "Null Value Counts",
                    "NaN Value Counts",
                    "Lower Bounds",
                    "Upper Bounds",
                    "Key Metadata",
                    "Split Offsets",
                    "Equality IDs",
                    "Sort Order ID",
                ],
                "desc": "Data files in the current snapshot.",
            },
            "$entries": {
                "cols": [
                    "Status",
                    "Snapshot ID",
                    "Sequence Number",
                    "File Sequence Number",
                    "Data File",
                    "Readable Metrics",
                ],
                "desc": "Manifest entries (data/delete files) for the current snapshot.",
            },
            "$all_entries": {
                "cols": [
                    "Status",
                    "Snapshot ID",
                    "Sequence Number",
                    "File Sequence Number",
                    "Data File",
                    "Readable Metrics",
                ],
                "desc": "Manifest entries (data/delete files) for all snapshots.",
            },
            "$refs": {
                "cols": [
                    "Name",
                    "Type",
                    "Snapshot ID",
                    "Max Reference Age (ms)",
                    "Min Snapshots to Keep",
                    "Max Snapshot Age (ms)",
                ],
                "desc": "Table references (branches and tags).",
            },
        }

        tab_names = ["SHOW DDL"] + list(metadata_tables.keys())
        meta_tabs = st.tabs(tab_names)

        # Show DDL Tab
        with meta_tabs[0]:
            st.markdown("#### `SHOW CREATE TABLE`")
            try:
                # Ensure correct quoting for schema and table names
                ddl_query = f'SHOW CREATE TABLE "{selected_schema}"."{selected_table}"'
                logger.info(f"Executing: {ddl_query}")
                ddl = cursor.execute(ddl_query).fetchall()[0][0]
                st.code(ddl, language="sql")
            except Exception as e:
                logger.error(f"Error executing SHOW CREATE TABLE: {e}", exc_info=True)
                st.error(f"Error loading table DDL: {e}")

        # Loop through metadata tables for other tabs
        for i, (meta_name, meta_info) in enumerate(metadata_tables.items()):
            with meta_tabs[i + 1]:  # Offset by 1 due to DDL tab
                st.markdown(f"#### `{meta_name}`")
                st.caption(meta_info["desc"])
                try:
                    # Construct query carefully, quoting table name with suffix
                    # Catalog and schema should be part of the connection or prefixed if needed
                    query = f'SELECT * FROM "{selected_schema}"."{selected_table}{meta_name}"'
                    logger.info(f"Executing: {query}")

                    df = pd.read_sql(query, conn)
                    df.drop(
                        columns=["partition_summaries"], inplace=True, errors="ignore"
                    )
                    display_dataframe(df)  # Use helper to display

                except Exception as e:
                    logger.error(
                        f"Error loading metadata table {meta_name}: {e}", exc_info=True
                    )
                    st.error(f"Error loading `{meta_name}`: {e}")

        st.divider()

        # --- Data Profiling Section (Optional) ---
        st.subheader("🔬 Data Profiling (Sample)")
        profile_limit = st.number_input(
            "Number of rows to profile",
            min_value=100,
            max_value=10000,
            value=1000,
            step=100,
            help="Limits the data fetched for profiling.",
        )
        if st.button("📊 Generate Profile Report (Sample)", use_container_width=True):
            st.warning(
                "Profiling fetches data and can be slow on large tables, even with limits."
            )
            with st.spinner(
                f"Fetching {profile_limit} rows and generating profile report..."
            ):
                try:
                    # Import profiling libraries here to avoid loading them if not used
                    from streamlit_ydata_profiling import st_profile_report
                    from ydata_profiling import ProfileReport

                    query = f'SELECT * FROM "{selected_schema}"."{selected_table}" LIMIT {profile_limit}'
                    logger.info(f"Executing profiling query: {query}")
                    # Use connection object directly with pandas for type handling
                    df_sample = pd.read_sql(query, conn)
                    st.success(f"Fetched {len(df_sample)} rows for profiling.")

                    if not df_sample.empty:
                        pr = ProfileReport(
                            df_sample,
                            title=f"Data Profiling Report (Sample) - {selected_schema}.{selected_table}",
                            explorative=True,
                            minimal=True,  # Use minimal mode for faster reports
                        )
                        st_profile_report(pr, navbar=True)
                        # Optionally show the sampled data
                        # with st.expander("View Sampled Data Used for Profiling"):
                        #    st.dataframe(df_sample)
                    else:
                        st.warning("No data returned for profiling.")

                except ImportError:
                    st.error(
                        "Please install 'ydata-profiling' and 'streamlit-ydata-profiling' to use this feature."
                    )
                except Exception as e:
                    logger.error(f"Error generating profile report: {e}", exc_info=True)
                    st.error(f"Error generating profile report: {e}")

    elif not selected_schema:
        st.info("Please select a schema from the sidebar.")
    # If schema selected but no table selected (or error fetching tables)
    elif not selected_table:
        st.info(
            f"Please select a table from schema '{selected_schema}' in the sidebar, or check if tables exist."
        )


if __name__ == "__main__":
    main()
