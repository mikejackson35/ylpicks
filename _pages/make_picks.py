import streamlit as st
from datetime import datetime, timezone


def safe_key(s: str) -> str:
    import re
    s = s.replace(" ", "_").replace("@", "at")
    return re.sub(r"[^0-9a-zA-Z_]", "", s)


def show(conn, cursor, username):
    
    # Get current tournament (most recent tournament that hasn't locked yet)
    now = datetime.now(timezone.utc)
    
    cursor.execute("""
        SELECT tournament_id, name, start_time 
        FROM tournaments 
        WHERE start_time >= %s - INTERVAL '1 day'
        ORDER BY start_time ASC
        LIMIT 1
    """, (now,))
    
    tournament = cursor.fetchone()
    
    if not tournament:
        st.warning("No upcoming tournament available for picks")
        return
    
    tournament_id = tournament["tournament_id"]
    st.title("Make Picks")
    st.subheader(tournament["name"])
    
    st.sidebar.divider()

    # Get tournament start time to lock picks
    start_time = tournament["start_time"]
    locked = start_time and now >= start_time

    st.write("")

    if locked:
        st.warning("⏰ Picks are locked - tournament has started")
        st.write("")
        
        # Show locked picks
        for tier_number in range(1, 7):
            st.subheader(f"Tier {tier_number}")
            
            cursor.execute("""
                SELECT player_id FROM picks
                WHERE username=%s AND tournament_id=%s AND tier_number=%s
            """, (username, tournament_id, tier_number))
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute("""
                    SELECT p.player_id, p.name
                    FROM weekly_tiers t
                    JOIN players p ON CAST(p.player_id AS TEXT) = CAST(t.player_id AS TEXT)
                    WHERE t.tournament_id=%s AND t.tier_number=%s
                """, (tournament_id, tier_number))
                players = cursor.fetchall()
                player_options = {p["name"]: p["player_id"] for p in players}
                
                locked_name = next((name for name, pid in player_options.items() if pid == existing["player_id"]), "Unknown")
                st.info(f"Your locked pick: **{locked_name}**")
            else:
                st.warning("No pick submitted")
        
        return

    # Tournament not locked - show selection form
    user_picks = {}
    
    for tier_number in range(1, 7):
        st.subheader(f"Tier {tier_number}")

        # Get players for this tier
        cursor.execute("""
            SELECT p.player_id, p.name
            FROM weekly_tiers t
            JOIN players p ON CAST(p.player_id AS TEXT) = CAST(t.player_id AS TEXT)
            WHERE t.tournament_id=%s AND t.tier_number=%s
        """, (tournament_id, tier_number))
        players = cursor.fetchall()
        
        if not players:
            st.info("No players assigned to this tier")
            user_picks[tier_number] = None
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

        choice_name = None
        # If existing pick exists, get name
        for name, pid in player_options.items():
            if pid == existing_pick:
                choice_name = name

        choice_name = st.selectbox(
            "",
            [""] + list(player_options.keys()),
            index=(list(player_options.keys()).index(choice_name)+1 if choice_name else 0),
            key=f"pick_{tournament_id}_tier{tier_number}_{safe_key(username)}"
        )
        
        user_picks[tier_number] = player_options.get(choice_name) if choice_name else None

    st.write("")
    st.write("---")
    
    # Validation check
    missing_tiers = [tier for tier, pick in user_picks.items() if pick is None]
    
    if missing_tiers:
        st.warning(f"⚠️ Please select players for all tiers. Missing: Tier {', Tier '.join(map(str, missing_tiers))}")
    
    # Single save button
    if st.button("💾 Save All Picks", type="primary", disabled=bool(missing_tiers)):
        # Delete all existing picks for this tournament
        cursor.execute("""
            DELETE FROM picks
            WHERE username=%s AND tournament_id=%s
        """, (username, tournament_id))
        
        # Insert all new picks
        for tier_number, player_id in user_picks.items():
            if player_id:  # Should always be true due to validation
                cursor.execute("""
                    INSERT INTO picks (username, tournament_id, tier_number, player_id, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                """, (username, tournament_id, tier_number, player_id, now.isoformat()))
        
        conn.commit()
        st.success("✅ All picks saved successfully!")
        st.rerun()