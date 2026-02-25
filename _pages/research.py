import streamlit as st
import pandas as pd


def show(conn, cursor):

    st.subheader("Research")
    st.caption("Last 6 Months")

    cursor.execute("""
        SELECT "Player", "Events", "SG Putt", "SG ARG", "SG APP", "SG OTT", "SG T2G", "SG Total"
        FROM research
        ORDER BY "SG T2G" DESC NULLS LAST
    """)
    rows = cursor.fetchall()

    if not rows:
        st.info("No research data available.")
        return

    df = pd.DataFrame(rows)
    df = df.rename(columns={"SG Putt": "Putt", "SG ARG": "ARG", "SG APP": "APP", "SG OTT": "OTT", "SG T2G": "T2G", "SG Total": "Total"})

    SG_COLS = ["Putt", "ARG", "APP", "OTT", "T2G", "Total"]

    for c in SG_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
    df["Events"] = pd.to_numeric(df["Events"], errors="coerce")

    column_config = {
        "Events": st.column_config.NumberColumn("Events", format="%d"),
        **{c: st.column_config.NumberColumn(c, format="%.10g") for c in SG_COLS}
    }

    styled = df.style.background_gradient(subset=["T2G"], cmap="RdYlGn", vmin=-4, vmax=4)

    height = (len(df) + 1) * 35 + 3
    st.dataframe(styled, hide_index=True, use_container_width=True, height=height, column_config=column_config)
