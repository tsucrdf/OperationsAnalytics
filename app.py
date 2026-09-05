import re

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Conductor Report Board", page_icon="🚌", layout="wide")

RIDER_COLS = [
    "No. of Pass",
    "No. of Child Pass",
    "No. of Handicapped Pass",
    "No. of Concession Pass",
]

ROUTE_STRIP_PATTERN = r"_(up|down)|\s(up|down)|_STL|[+-]"

CANONICAL_COLS = ["Date", "Bus Number", "Route Number", "Revenue", "Pass Category"] + RIDER_COLS


def find_col(columns, candidates):
    """Case/whitespace-tolerant column lookup."""
    lookup = {c.strip().lower(): c for c in columns}
    for cand in candidates:
        hit = lookup.get(cand.strip().lower())
        if hit:
            return hit
    return None


@st.cache_data(show_spinner=False)
def load_file(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename each file's columns to a shared canonical name (tolerant of
    spacing/casing differences between reports) so files from different
    exports line up correctly when merged."""
    cols = df.columns.tolist()
    rename_map = {}
    for canon in CANONICAL_COLS:
        found = find_col(cols, [canon])
        if found and found != canon:
            rename_map[found] = canon
    return df.rename(columns=rename_map)


def merge_uploaded_files(uploaded_files):
    """Load, normalize, and concatenate multiple report files into one
    DataFrame. Returns (merged_df, per_file_summary, per_file_errors)."""
    frames = []
    summary = []
    errors = []

    for f in uploaded_files:
        try:
            raw = load_file(f)
            norm = normalize_columns(raw)
            norm["Source File"] = f.name
            frames.append(norm)
            summary.append((f.name, len(norm)))
        except Exception as e:
            errors.append((f.name, str(e)))

    if not frames:
        return None, summary, errors

    merged = pd.concat(frames, ignore_index=True, sort=False)
    return merged, summary, errors


def analyze(df: pd.DataFrame):
    cols = df.columns.tolist()

    date_col = find_col(cols, ["Date"])
    bus_col = find_col(cols, ["Bus Number"])
    route_col = find_col(cols, ["Route Number"])
    revenue_col = find_col(cols, ["Revenue"])
    category_col = find_col(cols, ["Pass Category"])
    rider_cols = [c for c in (find_col(cols, [r]) for r in RIDER_COLS) if c]

    missing = [
        label
        for label, col in [
            ("Date", date_col),
            ("Bus Number", bus_col),
            ("Route Number", route_col),
            ("Revenue", revenue_col),
        ]
        if col is None
    ]
    if missing:
        raise ValueError(f"Missing expected column(s): {', '.join(missing)}")

    df = df.copy()
    df[revenue_col] = pd.to_numeric(df[revenue_col], errors="coerce").fillna(0)
    for c in rider_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["ridership"] = df[rider_cols].sum(axis=1) if rider_cols else 0

    df["strp_route"] = (
        df[route_col]
        .astype(str)
        .str.replace(ROUTE_STRIP_PATTERN, "", regex=True, case=False)
        .str.strip()
    )

    buses_per_day = df.groupby(date_col)[bus_col].nunique()
    routes_per_day = df.groupby(date_col)["strp_route"].nunique()
    revenue_per_day = df.groupby(date_col)[revenue_col].sum()
    ridership_per_day = df.groupby(date_col)["ridership"].sum()

    daily = pd.DataFrame(
        {
            "Buses": buses_per_day,
            "Routes": routes_per_day,
            "Revenue": revenue_per_day,
            "Ridership": ridership_per_day,
        }
    )

    has_category = category_col is not None
    if has_category:
        cat_norm = df[category_col].astype(str).str.strip().str.lower()

        online_mask = cat_norm == "online"
        cash_mask = cat_norm == "cash"

        daily["Online Revenue"] = df[online_mask].groupby(date_col)[revenue_col].sum()
        daily["Online Ridership"] = df[online_mask].groupby(date_col)["ridership"].sum()
        daily["Cash Revenue"] = df[cash_mask].groupby(date_col)[revenue_col].sum()
        daily["Cash Ridership"] = df[cash_mask].groupby(date_col)["ridership"].sum()
        daily = daily.fillna(0)

    daily = daily.sort_index()
    daily.index.name = "Date"
    return daily.reset_index(), has_category


def main():
    st.title("🚌 Conductor Report Board")
    st.caption(
        "Upload one or more conductor ticketing reports (CSV or Excel) to see buses, "
        "routes, revenue and ridership per day — split by online and cash sales. "
        "Multiple files are merged automatically before analysis."
    )

    uploaded_files = st.file_uploader(
        "Drop one or more reports here",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        st.info("Waiting for a file. Expected columns: Date, Bus Number, Route Number, "
                 "Revenue, Pass Category, and the pass-count columns. Upload several "
                 "files at once (e.g. one per day or per depot) and they'll be merged "
                 "before analysis.")
        return

    raw_df, file_summary, file_errors = merge_uploaded_files(uploaded_files)

    for name, err in file_errors:
        st.warning(f"Skipped **{name}** — couldn't read it: {err}")

    if raw_df is None:
        st.error("None of the uploaded files could be read.")
        return

    try:
        daily, has_category = analyze(raw_df)
    except Exception as e:
        st.error(f"Couldn't analyze the merged data: {e}")
        return

    if len(uploaded_files) > 1:
        st.success(
            f"Merged **{len(file_summary)}** file(s) — {len(raw_df):,} total rows, "
            f"{len(daily)} days"
        )
        with st.expander("Rows contributed per file"):
            st.dataframe(
                pd.DataFrame(file_summary, columns=["File", "Rows"]),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.success(f"Loaded **{uploaded_files[0].name}** — {len(raw_df):,} rows, {len(daily)} days")

    total_revenue = daily["Revenue"].sum()
    total_ridership = daily["Ridership"].sum()
    avg_buses = daily["Buses"].mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Days covered", len(daily))
    c2.metric("Total revenue", f"₹{total_revenue:,.0f}")
    c3.metric("Total ridership", f"{total_ridership:,.0f}")
    c4.metric("Avg. buses / day", f"{avg_buses:.1f}")

    st.subheader("Daily board")
    st.dataframe(daily, use_container_width=True, hide_index=True)

    st.subheader("Trends")
    t1, t2 = st.columns(2)
    with t1:
        st.caption("Revenue per day")
        st.bar_chart(daily.set_index("Date")["Revenue"])
    with t2:
        st.caption("Ridership per day")
        st.line_chart(daily.set_index("Date")["Ridership"])

    t3, t4 = st.columns(2)
    with t3:
        st.caption("Buses & routes in service")
        st.line_chart(daily.set_index("Date")[["Buses", "Routes"]])
    with t4:
        if has_category:
            st.caption("Online vs. cash revenue")
            st.bar_chart(daily.set_index("Date")[["Online Revenue", "Cash Revenue"]])
        else:
            st.caption("Online vs. cash revenue")
            st.write("No 'Pass Category' column found in this file — skipping split.")

    st.download_button(
        "Download daily board as CSV",
        daily.to_csv(index=False).encode("utf-8"),
        file_name="daily_board.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()