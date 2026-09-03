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
        "Upload a conductor ticketing report (CSV or Excel) to see buses, routes, "
        "revenue and ridership per day — split by online and cash sales."
    )

    uploaded_file = st.file_uploader("Drop a report here", type=["csv", "xlsx", "xls"])

    if uploaded_file is None:
        st.info("Waiting for a file. Expected columns: Date, Bus Number, Route Number, "
                 "Revenue, Pass Category, and the pass-count columns.")
        return

    try:
        raw_df = load_file(uploaded_file)
        daily, has_category = analyze(raw_df)
    except Exception as e:
        st.error(f"Couldn't read that file: {e}")
        return

    st.success(f"Loaded **{uploaded_file.name}** — {len(raw_df):,} rows, {len(daily)} days")

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
