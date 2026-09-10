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

# Channel column pairs in the "conductor summary" report: (channel label, passenger-count candidates, amount candidates)
CONDUCTOR_AMOUNT_CHANNELS = [
    ("Cash", ["Cash(Passenger)", "Cash (Passenger)"], ["Cash(Amount)", "Cash (Amount)"]),
    ("Online", ["Online(Passenger)", "Online (Passenger)"], ["Online(Amount)", "Online (Amount)"]),
    ("Katch Card", ["Katch Card(Passenger)", "Katch Card (Passenger)"], ["Katch Card(Amount)", "Katch Card (Amount)"]),
    ("Insta Card", ["Insta Card(Passenger)", "Insta Card (Passenger)"], ["Insta Card(Amount)", "Insta Card (Amount)"]),
]
# Count-only columns in the conductor summary report (no associated amount column).
CONDUCTOR_COUNT_ONLY_CHANNELS = [
    ("Scan (App Ticket)", ["Scan(App Ticket)", "Scan (App Ticket)"]),
    ("Scan Pass (App Ticket)", ["Scan Pass(App Ticket)", "Scan Pass (App Ticket)"]),
]

# Metrics requested that have no source in any supported report format — kept as
# empty columns in the daily board for the user to fill in manually.
MANUAL_ONLY_COLUMNS = [
    "Buses Sanctioned",
    "Buses Received",
    "Bus Type",
    "Assured Kms",
    "Operated Kms",
    "EPKM",
    "No. of Breakdowns",
    "No. of Road Accidents",
    "Fleet Availability (%)",
    "Vehicle Utilisation (km/day)",
    "Punctuality % (Start)",
    "Punctuality % (Arrival)",
    "No. of Drivers Utilised Per day",
]


def find_col(columns, candidates):
    """Case/whitespace-tolerant column lookup. Falls back to a prefix match so
    headers with extra trailing qualifiers (e.g. "Cash(Passenger) (Conductor book)")
    still resolve to the expected canonical field."""
    lookup = {c.strip().lower(): c for c in columns}
    for cand in candidates:
        hit = lookup.get(cand.strip().lower())
        if hit:
            return hit
    for cand in candidates:
        key = cand.strip().lower()
        for col in columns:
            if col.strip().lower().startswith(key):
                return col
    return None


def strip_route(series):
    return series.astype(str).str.replace(ROUTE_STRIP_PATTERN, "", regex=True, case=False).str.strip()


@st.cache_data(show_spinner=False)
def load_file(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def detect_format(df):
    """Identify which of the supported report layouts a file matches."""
    cols = df.columns.tolist()
    if find_col(cols, ["Ticket No"]) and find_col(cols, ["Payment Type"]) and find_col(cols, ["Booked Date"]):
        return "ticket_detail"
    if (
        find_col(cols, ["Conductor Name"])
        and find_col(cols, ["Date"])
        and any(find_col(cols, amt) for _, _, amt in CONDUCTOR_AMOUNT_CHANNELS)
    ):
        return "conductor_summary"
    if find_col(cols, ["Bus Number"]) and find_col(cols, ["Route Number"]) and find_col(cols, ["Revenue"]):
        return "canonical"
    return None


def extract_canonical(df):
    """Original per-record report: Date, Bus Number, Route Number, Revenue, Pass Category, rider counts."""
    cols = df.columns.tolist()
    date_col = find_col(cols, ["Date"])
    bus_col = find_col(cols, ["Bus Number"])
    route_col = find_col(cols, ["Route Number"])
    revenue_col = find_col(cols, ["Revenue"])
    category_col = find_col(cols, ["Pass Category"])
    rider_cols = [c for c in (find_col(cols, [r]) for r in RIDER_COLS) if c]

    ridership = pd.Series(0, index=df.index, dtype=float)
    for c in rider_cols:
        ridership = ridership + pd.to_numeric(df[c], errors="coerce").fillna(0)

    return pd.DataFrame(
        {
            "Date": pd.to_datetime(df[date_col], errors="coerce").dt.date,
            "Bus Number": df[bus_col],
            "Route": strip_route(df[route_col]),
            "Conductor": pd.NA,
            "Payment Channel": df[category_col].astype(str).str.strip() if category_col else "Unspecified",
            "Revenue": pd.to_numeric(df[revenue_col], errors="coerce").fillna(0),
            "Ridership": ridership,
            "Tickets": 1,
        }
    )


def extract_ticket_detail(df):
    """Per-ticket sale report: Bus Number, Route Name, Payment Type, Booked Date, adult/child counts."""
    cols = df.columns.tolist()
    bus_col = find_col(cols, ["Bus Number"])
    route_col = find_col(cols, ["Route Name"])
    conductor_col = find_col(cols, ["Conductor Name"])
    payment_col = find_col(cols, ["Payment Type"])
    status_col = find_col(cols, ["Payment Status"])
    booked_col = find_col(cols, ["Booked Date"])
    amount_col = find_col(cols, ["Total"]) or find_col(cols, ["Amount"])
    adult_col = find_col(cols, ["Total Adult"])
    child_col = find_col(cols, ["Total Child"])

    d = df
    if status_col:
        d = d[d[status_col].astype(str).str.strip().str.lower() == "success"]

    adult = pd.to_numeric(d[adult_col], errors="coerce").fillna(0) if adult_col else 0
    child = pd.to_numeric(d[child_col], errors="coerce").fillna(0) if child_col else 0

    return pd.DataFrame(
        {
            "Date": pd.to_datetime(d[booked_col], errors="coerce").dt.date,
            "Bus Number": d[bus_col] if bus_col else pd.NA,
            "Route": strip_route(d[route_col]) if route_col else pd.NA,
            "Conductor": d[conductor_col].astype(str).str.strip() if conductor_col else pd.NA,
            "Payment Channel": d[payment_col].astype(str).str.strip() if payment_col else "Unspecified",
            "Revenue": pd.to_numeric(d[amount_col], errors="coerce").fillna(0) if amount_col else 0,
            "Ridership": adult + child,
            "Tickets": 1,
        }
    )


def extract_conductor_summary(df):
    """Per-conductor daily settlement report, split by payment channel (wide) — melted to long form.

    No Bus Number / Route Number is present in this report, so those fields are
    left null for its rows and simply don't contribute to the per-bus/per-route metrics.
    """
    cols = df.columns.tolist()
    date_col = find_col(cols, ["Date"])
    conductor_col = find_col(cols, ["Conductor Name"])

    dates = pd.to_datetime(df[date_col], errors="coerce").dt.date
    conductors = df[conductor_col].astype(str).str.strip() if conductor_col else pd.Series(pd.NA, index=df.index)

    frames = []
    for channel, pax_candidates, amt_candidates in CONDUCTOR_AMOUNT_CHANNELS:
        pax_col = find_col(cols, pax_candidates)
        amt_col = find_col(cols, amt_candidates)
        if not pax_col and not amt_col:
            continue
        pax = pd.to_numeric(df[pax_col], errors="coerce").fillna(0) if pax_col else 0
        amt = pd.to_numeric(df[amt_col], errors="coerce").fillna(0) if amt_col else 0
        frames.append(
            pd.DataFrame(
                {
                    "Date": dates,
                    "Bus Number": pd.NA,
                    "Route": pd.NA,
                    "Conductor": conductors,
                    "Payment Channel": channel,
                    "Revenue": amt,
                    "Ridership": pax,
                    "Tickets": pd.NA,
                }
            )
        )

    for channel, candidates in CONDUCTOR_COUNT_ONLY_CHANNELS:
        c = find_col(cols, candidates)
        if not c:
            continue
        cnt = pd.to_numeric(df[c], errors="coerce").fillna(0)
        frames.append(
            pd.DataFrame(
                {
                    "Date": dates,
                    "Bus Number": pd.NA,
                    "Route": pd.NA,
                    "Conductor": conductors,
                    "Payment Channel": channel,
                    "Revenue": 0,
                    "Ridership": cnt,
                    "Tickets": cnt,
                }
            )
        )

    if not frames:
        return pd.DataFrame(columns=["Date", "Bus Number", "Route", "Conductor", "Payment Channel", "Revenue", "Ridership", "Tickets"])
    return pd.concat(frames, ignore_index=True)


EXTRACTORS = {
    "canonical": extract_canonical,
    "ticket_detail": extract_ticket_detail,
    "conductor_summary": extract_conductor_summary,
}


def merge_uploaded_files(uploaded_files):
    """Load, detect format, normalize each file to a common transaction layout, and
    concatenate. Returns (merged_df, per_file_summary, per_file_errors)."""
    frames = []
    summary = []
    errors = []

    for f in uploaded_files:
        try:
            raw = load_file(f)
            fmt = detect_format(raw)
            if fmt is None:
                errors.append((f.name, "unrecognized report format — none of the expected column sets were found"))
                continue
            norm = EXTRACTORS[fmt](raw)
            norm["Source File"] = f.name
            frames.append(norm)
            summary.append((f.name, fmt, len(norm)))
        except Exception as e:
            errors.append((f.name, str(e)))

    if not frames:
        return None, summary, errors

    merged = pd.concat(frames, ignore_index=True, sort=False)
    return merged, summary, errors


def nunique_or_na(series):
    non_null = series.dropna()
    return non_null.nunique() if len(non_null) else pd.NA


def analyze(df: pd.DataFrame):
    if df.empty:
        raise ValueError("No usable rows found in the uploaded file(s).")

    d = df.copy()
    d["Revenue"] = pd.to_numeric(d["Revenue"], errors="coerce").fillna(0)
    d["Ridership"] = pd.to_numeric(d["Ridership"], errors="coerce").fillna(0)

    grouped = d.groupby("Date")

    daily = pd.DataFrame(
        {
            "Buses Deployed on-road": grouped["Bus Number"].apply(nunique_or_na),
            "No. of Routes Operational": grouped["Route"].apply(nunique_or_na),
            "Total Earnings": grouped["Revenue"].sum(),
            "Ridership per day": grouped["Ridership"].sum(),
            "No. of Conductors Utilised Per day": grouped["Conductor"].apply(nunique_or_na),
        }
    )

    buses_numeric = pd.to_numeric(daily["Buses Deployed on-road"], errors="coerce")
    daily["Ridership per Bus"] = (daily["Ridership per day"] / buses_numeric).where(buses_numeric > 0).round(1)
    daily["Revenue Per Bus Per Day"] = (daily["Total Earnings"] / buses_numeric).where(buses_numeric > 0).round(2)

    for col in MANUAL_ONLY_COLUMNS:
        daily[col] = pd.NA

    # Per payment-channel breakdown, kept separate (not bucketed into Cash/Digital/NCMC).
    ticket_pivot = d.pivot_table(
        index="Date", columns="Payment Channel", values="Tickets", aggfunc=lambda s: s.sum(min_count=1)
    )
    revenue_pivot = d.pivot_table(
        index="Date", columns="Payment Channel", values="Revenue", aggfunc=lambda s: s.sum(min_count=1)
    )
    channels = sorted(set(ticket_pivot.columns) | set(revenue_pivot.columns))
    revenue_channel_cols = []
    for ch in channels:
        tickets_col = f"No. of Daily Ticketing ({ch})"
        revenue_col = f"Revenue ({ch})"
        daily[tickets_col] = ticket_pivot[ch] if ch in ticket_pivot.columns else pd.NA
        daily[revenue_col] = revenue_pivot[ch] if ch in revenue_pivot.columns else pd.NA
        revenue_channel_cols.append(revenue_col)

    ordered_cols = [
        "Buses Sanctioned",
        "Buses Received",
        "Buses Deployed on-road",
        "Bus Type",
        "No. of Routes Operational",
        "Assured Kms",
        "Operated Kms",
        "Total Earnings",
        "EPKM",
        "Ridership per day",
        "Ridership per Bus",
        "No. of Breakdowns",
        "No. of Road Accidents",
        "Fleet Availability (%)",
        "Vehicle Utilisation (km/day)",
        "Punctuality % (Start)",
        "Punctuality % (Arrival)",
        "No. of Conductors Utilised Per day",
        "No. of Drivers Utilised Per day",
        "Revenue Per Bus Per Day",
    ] + [c for pair in zip(
        [f"No. of Daily Ticketing ({ch})" for ch in channels],
        [f"Revenue ({ch})" for ch in channels],
    ) for c in pair]

    daily = daily[ordered_cols].sort_index()
    daily.index.name = "Date"
    return daily.reset_index(), revenue_channel_cols


def main():
    st.title("🚌 Conductor Report Board")
    st.caption(
        "Upload one or more conductor/ticketing reports (CSV or Excel) to see fleet, "
        "revenue, ridership and payment-channel KPIs per day. Three report formats are "
        "supported and can be mixed and matched — the standard per-record report, the "
        "per-conductor daily settlement report, and the per-ticket driver/ticket-book "
        "report. Files are merged automatically before analysis."
    )

    uploaded_files = st.file_uploader(
        "Drop one or more reports here",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        st.info(
            "Waiting for a file. Supported formats: (1) Date/Bus Number/Route Number/"
            "Revenue/Pass Category records, (2) per-conductor daily settlement reports "
            "(Conductor Name, Date, Cash/Online/Katch Card/Insta Card amounts), or "
            "(3) per-ticket driver reports (Bus Number, Route Name, Payment Type, "
            "Booked Date). Upload several files at once and they'll be merged before analysis."
        )
        return

    raw_df, file_summary, file_errors = merge_uploaded_files(uploaded_files)

    for name, err in file_errors:
        st.warning(f"Skipped **{name}** — {err}")

    if raw_df is None:
        st.error("None of the uploaded files could be read.")
        return

    try:
        daily, revenue_channel_cols = analyze(raw_df)
    except Exception as e:
        st.error(f"Couldn't analyze the merged data: {e}")
        return

    if len(uploaded_files) > 1 or file_summary:
        st.success(
            f"Merged **{len(file_summary)}** file(s) — {len(raw_df):,} total rows, "
            f"{len(daily)} days"
        )
        with st.expander("Rows contributed per file"):
            st.dataframe(
                pd.DataFrame(file_summary, columns=["File", "Detected Format", "Rows"]),
                use_container_width=True,
                hide_index=True,
            )

    st.caption(
        "Columns with no data in any uploaded report (Buses Sanctioned, Buses Received, "
        "Bus Type, Assured/Operated Kms, EPKM, Breakdowns, Road Accidents, Fleet "
        "Availability, Vehicle Utilisation, Punctuality, Drivers Utilised) are left blank "
        "below for manual entry — they aren't present in any of the supported report formats."
    )

    total_revenue = daily["Total Earnings"].sum()
    total_ridership = daily["Ridership per day"].sum()
    avg_buses = pd.to_numeric(daily["Buses Deployed on-road"], errors="coerce").mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Days covered", len(daily))
    c2.metric("Total revenue", f"₹{total_revenue:,.0f}")
    c3.metric("Total ridership", f"{total_ridership:,.0f}")
    c4.metric("Avg. buses / day", f"{avg_buses:.1f}" if pd.notna(avg_buses) else "N/A")

    st.subheader("Daily board")
    st.dataframe(daily, use_container_width=True, hide_index=True)

    st.subheader("Trends")
    t1, t2 = st.columns(2)
    with t1:
        st.caption("Revenue per day")
        st.bar_chart(daily.set_index("Date")["Total Earnings"])
    with t2:
        st.caption("Ridership per day")
        st.line_chart(daily.set_index("Date")["Ridership per day"])

    t3, t4 = st.columns(2)
    with t3:
        st.caption("Buses & routes in service")
        chart_df = daily.set_index("Date")[["Buses Deployed on-road", "No. of Routes Operational"]].apply(
            pd.to_numeric, errors="coerce"
        )
        st.line_chart(chart_df)
    with t4:
        if revenue_channel_cols:
            st.caption("Revenue by payment channel")
            chart_df = daily.set_index("Date")[revenue_channel_cols].apply(pd.to_numeric, errors="coerce")
            st.bar_chart(chart_df)
        else:
            st.caption("Revenue by payment channel")
            st.write("No payment-channel information found in the uploaded file(s).")

    st.download_button(
        "Download daily board as CSV",
        daily.to_csv(index=False).encode("utf-8"),
        file_name="daily_board.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
