import streamlit as st
from datetime import datetime, timezone, timedelta


def show(conn, cursor):

    st.subheader("Admin")
    st.write(" ")

    # ----------------------------
    # TIER SETUP
    # ----------------------------
    st.markdown("**Set Up Tiers**")

    cursor.execute("""
        SELECT tournament_id, name, start_time
        FROM tournaments
        ORDER BY start_time ASC
    """)
    tournaments = cursor.fetchall()

    if not tournaments:
        st.info("No tournaments found.")
        return

    # Default to current/upcoming tournament
    now = datetime.now(timezone.utc)
    current_tid = None
    for t in tournaments:
        if t["start_time"] + timedelta(days=5) > now:
            current_tid = t["tournament_id"]
            break

    tourn_names = [t["name"] for t in tournaments]
    tourn_options = {t["name"]: t["tournament_id"] for t in tournaments}
    default_index = next((i for i, t in enumerate(tournaments) if t["tournament_id"] == current_tid), len(tournaments) - 1)

    selected_name = st.selectbox("Tournament", tourn_names, index=default_index, key="admin_tourn_select")
    selected_tid = tourn_options[selected_name]

    st.write("")

    # All players sorted by name
    cursor.execute("SELECT player_id, name FROM players ORDER BY name")
    all_players = cursor.fetchall()
    name_to_id = {p["name"]: str(p["player_id"]) for p in all_players}
    id_to_name = {str(p["player_id"]): p["name"] for p in all_players}
    player_names = list(name_to_id.keys())

    # Existing tiers for selected tournament
    cursor.execute("""
        SELECT tier_number, player_id
        FROM tournament_tiers
        WHERE tournament_id = %s
        ORDER BY tier_number
    """, (selected_tid,))
    existing_rows = cursor.fetchall()

    existing_by_tier = {}
    for row in existing_rows:
        t = int(row["tier_number"])
        pid = str(row["player_id"])
        existing_by_tier.setdefault(t, []).append(pid)

    tier_selections = {}
    for tier_num in range(1, 7):
        existing_pids = existing_by_tier.get(tier_num, [])
        existing_names = [id_to_name[pid] for pid in existing_pids if pid in id_to_name]

        tier_selections[tier_num] = st.multiselect(
            f"Tier {tier_num}",
            options=player_names,
            default=sorted(existing_names),
            key=f"admin_tier_{tier_num}_{selected_tid}"
        )

    st.write("")

    if st.button("💾 Save Tiers", type="primary", key="admin_save_tiers"):
        cursor.execute("DELETE FROM tournament_tiers WHERE tournament_id = %s", (selected_tid,))
        for tier_num, names in tier_selections.items():
            for name in names:
                pid = name_to_id[name]
                cursor.execute("""
                    INSERT INTO tournament_tiers (tournament_id, tier_number, player_id)
                    VALUES (%s, %s, %s)
                """, (selected_tid, tier_num, pid))
        conn.commit()
        st.success("✅ Tiers saved!")
        st.rerun()