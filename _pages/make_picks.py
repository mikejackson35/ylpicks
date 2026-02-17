import streamlit as st
from datetime import datetime, timezone


def safe_key(s: str) -> str:
    import re
    s = s.replace(" ", "_").replace("@", "at")
    return re.sub(r"[^0-9a-zA-Z_]", "", s)


def show(conn, cursor, username):
    
    col1, space, col2 = st.columns([2.25, .25, 2.50])
    with col1:
        st.title("Make Picks")
    with col2:
        # Select tournament
        cursor.execute("SELECT tournament_id, name, start_time FROM tournaments ORDER BY start_time")
        tournaments = cursor.fetchall()
        if not tournaments:
            st.warning("No tournaments available")
            return
        else:
            tournament_map = {t["name"]: t["tournament_id"] for t in tournaments}
            selected_name = st.selectbox("Tournament", list(tournament_map.keys()))
            tournament_id = tournament_map[selected_name]

    st.sidebar.divider()

    # Current time (UTC)
    now = datetime.now(timezone.utc)

    # Get tournament start time to lock picks
    cursor.execute("SELECT start_time FROM tournaments WHERE tournament_id=%s", (tournament_id,))
    tournament_info = cursor.fetchone()
    start_time = tournament_info["start_time"] if tournament_info else None
    locked = start_time and now >= start_time

    st.write("")

    # For each tier (1-5)
    for tier_number in range(1, 6):
        st.subheader(f"Tier {tier_number}")

        # Get players for this tier
        cursor.execute("""
            SELECT p.player_id, p.name
            FROM tiers t
            JOIN players p ON p.player_id = t.player_id
            WHERE t.tournament_id=%s AND t.tier_number=%s
        """, (tournament_id, tier_number))
        players = cursor.fetchall()
        if not players:
            st.info("No players assigned to this tier")
            continue

        # Get existing pick for this user/tier
        cursor.execute("""
            SELECT player_id FROM picks
            WHERE username=%s AND tournament_id=%s AND tier_number=%s
        """, (username, tournament_id, tier_number))
        existing = cursor.fetchone()
        existing_pick = existing["player_id"] if existing else None

        # Options
        player_options = {p["name"]: p["player_id"] for p in players}

        if not locked:
            choice_name = None
            # If existing pick exists, get name
            for name, pid in player_options.items():
                if pid == existing_pick:
                    choice_name = name

            choice_name = st.selectbox(
                "Select Player",
                [""] + list(player_options.keys()),
                index=(list(player_options.keys()).index(choice_name)+1 if choice_name else 0),
                key=f"pick_{tournament_id}_tier{tier_number}_{safe_key(username)}"
            )

            if st.button("Save", key=f"save_{tournament_id}_tier{tier_number}_{safe_key(username)}"):
                # Delete old pick
                cursor.execute("""
                    DELETE FROM picks
                    WHERE username=%s AND tournament_id=%s AND tier_number=%s
                """, (username, tournament_id, tier_number))
                # Insert new pick
                cursor.execute("""
                    INSERT INTO picks (username, tournament_id, tier_number, player_id, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                """, (username, tournament_id, tier_number, player_options.get(choice_name), now.isoformat()))
                conn.commit()
                st.success(f"Saved pick: {choice_name}")
                st.rerun()
        else:
            if existing_pick:
                # Display name for locked pick
                locked_name = next((name for name, pid in player_options.items() if pid == existing_pick), "Unknown")
                st.info(f"Your locked pick: **{locked_name}**")
            else:
                st.warning("No pick submitted")