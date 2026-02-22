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
            WHERE start_time <= %s + INTERVAL '3 days'
            AND start_time >= %s - INTERVAL '4 days'
            ORDER BY start_time DESC
            LIMIT 1
        """, (now, now))
    
    tournament = cursor.fetchone()
    
    if not tournament:
        st.warning("No upcoming tournament available for picks")
        return
    
    tournament_id = tournament["tournament_id"]
    st.subheader("Make Picks")
    st.write("Be sure to hit save!")
    
    st.sidebar.divider()

    # Get tournament start time to lock picks
    start_time = tournament["start_time"]
    locked = start_time and now >= start_time

    st.write("")

    if locked:
        st.warning("⏰ Picks are locked - tournament has started")
        st.write("")
        
        # Show locked picks in 2-column layout
        for tier_number in range(1, 7):
            col1, col2 = st.columns([1, 4])
            
            with col1:
                st.write(f"**Tier {tier_number}**")
            
            with col2:
                cursor.execute("""
                    SELECT player_id FROM user_picks
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
                    
                    locked_name = next((name for name, pid in player_options.items() if pid == str(existing["player_id"])), "Unknown")
                    st.info(f"**{locked_name}**")
                else:
                    st.warning("No pick submitted")
        
        return

    # Tournament not locked - show selection form in 2-column layout
    user_picks = {}
    
    for tier_number in range(1, 7):

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
            SELECT player_id FROM user_picks
            WHERE username=%s AND tournament_id=%s AND tier_number=%s
        """, (username, tournament_id, tier_number))
        existing = cursor.fetchone()
        existing_pick = str(existing["player_id"]) if existing else None

        # Options
        player_options = {p["name"]: p["player_id"] for p in players}
        choice_name = None
        # If existing pick exists, get name
        for name, pid in player_options.items():
            if pid == existing_pick:
                choice_name = name

        # 2-column layout: tier label + selectbox
        col1, col2 = st.columns([1, 6])
        
        with col1:
            st.write(f"**Tier {tier_number}**")

        with col2:
            choice_name = st.selectbox(
                "",  # Empty label since tier number is in col1
                [""] + list(player_options.keys()),
                index=(list(player_options.keys()).index(choice_name)+1 if choice_name else 0),
                key=f"pick_{tournament_id}_tier{tier_number}_{safe_key(username)}",
                label_visibility="collapsed"  # Hide the empty label completely
            )
            st.write("")  # Add spacing after selectbox
        
        user_picks[tier_number] = player_options.get(choice_name) if choice_name else None

    st.write("")
    st.write("")
    
    # Validation check
    missing_tiers = [tier for tier, pick in user_picks.items() if pick is None]
    
    if missing_tiers:
        st.warning(f"⚠️ Still Missing Tier {', Tier '.join(map(str, missing_tiers))}")
    
    # Single save button
    if st.button("💾 Save Picks", type="primary", disabled=bool(missing_tiers)):
        # Delete all existing picks for this tournament
        cursor.execute("""
            DELETE FROM user_picks
            WHERE username=%s AND tournament_id=%s
        """, (username, tournament_id))

        now = datetime.now(timezone.utc)
        # Insert all new picks
        for tier_number, player_id in user_picks.items():
            if player_id:  # Should always be true due to validation
                # Create user_picks_id as concatenation
                user_picks_id = f"{tournament_id}_{tier_number}_{username}"
                
                cursor.execute("""
                    INSERT INTO user_picks (username, tournament_id, tier_number, player_id, timestamp, user_picks_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (username, tournament_id, tier_number, player_id, now.isoformat(), user_picks_id))
        
        conn.commit()
        st.success("✅ All picks saved successfully!")
        st.rerun()