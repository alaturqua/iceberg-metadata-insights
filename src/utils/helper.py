import pandas as pd
import streamlit as st
import json
from typing import Optional
import math


# --- Helper Functions ---
def safe_float(value, default=0.0) -> float:
    """Safely convert value to float, return default if error."""
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def display_dataframe(df: pd.DataFrame):
    """Helper to display DataFrame with potential JSON expansion."""
    if df.empty:
        st.info("No data available for this metadata table.")
        return

    # Try to detect columns that might contain JSON/Map data for better display
    json_like_cols = []
    for col in df.columns:
        # Simple check: if a value starts with { or [ it *might* be JSON-like
        # More robust checks could involve trying json.loads on sample values
        if df[col].dtype == "object":
            try:
                # Check first non-null value
                first_val = df[col].dropna().iloc[0]
                if isinstance(first_val, (str)) and (
                    first_val.strip().startswith("{")
                    or first_val.strip().startswith("[")
                ):
                    json_like_cols.append(col)
            except IndexError:
                pass  # Column is all null

    if json_like_cols:
        with st.expander("Detailed View (with JSON expansion)"):
            st.dataframe(df, use_container_width=True)  # Show raw first
            for col_name in json_like_cols:
                st.write(f"**Expanded '{col_name}':**")
                # Display each JSON field prettily
                for index, row in df.iterrows():
                    try:
                        # Attempt to parse if it's a string representation
                        data_to_show = row[col_name]
                        if isinstance(data_to_show, str):
                            parsed_data = json.loads(data_to_show)
                            st.json(parsed_data, expanded=False)
                        elif isinstance(data_to_show, (dict, list)):  # Already parsed?
                            st.json(data_to_show, expanded=False)
                        else:
                            st.text(str(data_to_show))  # Display as text if not JSON
                    except (json.JSONDecodeError, TypeError, IndexError):
                        st.text(
                            f"Row {index}: {str(row[col_name])} (Not valid JSON or empty)"
                        )
                    except Exception as e:
                        st.text(f"Row {index}: Error processing - {e}")
    else:
        st.dataframe(df, use_container_width=True)


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
