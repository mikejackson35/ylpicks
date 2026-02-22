import streamlit as st
import pandas as pd
from datetime import datetime, timezone


def show(conn, cursor, api_key):

    # Get current tournament (most recent tournament that has started or will start soon)
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
        st.warning("No current tournament available")
        return
    
    tournament_id = tournament["tournament_id"]
    st.write(f"**{tournament['name']}**")
    
    st.write("")

    # Get tournament start time
    start_time = tournament["start_time"]
    locked = start_time and now < start_time  # locked = True if tournament hasn't started

    # 1️⃣ Get all users
    cursor.execute("SELECT username, name FROM users")
    users = cursor.fetchall()
    usernames = [u["username"] for u in users]
    name_map = {u["username"]: u["name"] for u in users}

    # 2️⃣ Get picks for this tournament
    cursor.execute("""
        SELECT username, tier_number, player_id
        FROM user_picks
        WHERE tournament_id=%s
    """, (tournament_id,))
    rows = cursor.fetchall()

    # 3️⃣ Build lookup: username -> tier_number -> player_id
    pick_map = {u: {tier: None for tier in range(1, 7)} for u in usernames}
    for row in rows:
        pick_map[row["username"]][row["tier_number"]] = row["player_id"]

    # 4️⃣ Build display table
    table = []
    for user in users:
        username = user["username"]
        row_data = {"User": user["name"]}

        for tier_number in range(1, 7):
            pick_id = pick_map[username][tier_number]

            if pick_id and not locked:
                # Show pick if tournament started
                cursor.execute("SELECT name_last FROM players WHERE player_id=%s", (pick_id,))
                player = cursor.fetchone()
                pick_name = player["name_last"] if player else "Unknown"
                row_data[f"Tier {tier_number}"] = pick_name
            else:
                # Tournament not started or pick not made
                # row_data[f"Tier {tier_number}"] = "🔒"
                row_data[f"Tier {tier_number}"] = "-"

        table.append(row_data)

    # 5️⃣ Build DataFrame
    df = pd.DataFrame(table)

    # Get leaderboard to highlight leaders in each tier and track missed cuts
    try:
        from utils.leaderboard_api import get_live_leaderboard
        leaderboard_for_highlight = get_live_leaderboard(api_key)

        # Create score lookup and cut status
        score_lookup = {}
        cut_status = {}  # player_id -> True if missed cut
        
        for _, lb_row in leaderboard_for_highlight.iterrows():
            player_id = str(lb_row["PlayerID"])
            score = lb_row["Score"]
            status = str(lb_row.get("Status", "active")).lower()
            
            # Track missed cuts
            cut_status[player_id] = (status == "cut")
            
            if score == "E":
                numeric_score = 0
            elif isinstance(score, str):
                try:
                    numeric_score = int(score.replace("+", ""))
                except:
                    numeric_score = 999
            else:
                numeric_score = 999
            score_lookup[player_id] = numeric_score

        # Build a reverse lookup: player_name -> player_id
        name_to_id = {}
        for username in usernames:
            for tier_num in range(1, 7):
                pick_id = pick_map[username][tier_num]
                if pick_id:
                    cursor.execute("SELECT name_last FROM players WHERE player_id=%s", (pick_id,))
                    player = cursor.fetchone()
                    if player:
                        name_to_id[player["name_last"]] = str(pick_id)

    except Exception as e:
        score_lookup = {}
        name_to_id = {}
        cut_status = {}

# Calculate cumulative scores for each user
    user_scores = {}
    numeric_scores = {}

    for user in users:
        username = user["username"]
        user_name = user["name"]
        total_score = 0
        valid_scores = 0  # Track how many valid scores we have

        for tier_number in range(1, 7):
            pick_id = pick_map[username][tier_number]
            if pick_id and str(pick_id) in score_lookup:
                score = score_lookup[str(pick_id)]
                if score != 999:  # Only count real scores, not placeholder
                    total_score += score
                    valid_scores += 1

        # Only show score if we have valid scores, otherwise show "E"
        if valid_scores == 0:
            numeric_scores[user_name] = 0
            user_scores[user_name] = "E"
        else:
            numeric_scores[user_name] = total_score
            if total_score == 0:
                score_display = "E"
            elif total_score < 0:
                score_display = str(total_score)
            else:
                score_display = f"+{total_score}"
            user_scores[user_name] = score_display

# Find user(s) with best score
    if numeric_scores:
        best_score = min(numeric_scores.values())
        leaders = [name for name, score in numeric_scores.items() if score == best_score]
    else:
        leaders = []

# Calculate weekly points for each user
    weekly_points = {}
    for user in users:
        username = user["username"]
        user_name = user["name"]
        points = 0
        
        # Count tier wins
        for tier_number in range(1, 7):
            pick_id = pick_map[username][tier_number]
            if pick_id and str(pick_id) in score_lookup:
                player_id = str(pick_id)
                
                # Find tier leader
                tier_picks = {}
                for u in usernames:
                    u_pick = pick_map[u].get(tier_number)
                    if u_pick and str(u_pick) in score_lookup:
                        tier_picks[u] = score_lookup[str(u_pick)]
                
                if tier_picks:
                    tier_best = min(tier_picks.values())
                    if score_lookup[player_id] == tier_best:
                        points += 1  # +1 for tier win
                
                # Check for missed cut
                if cut_status.get(player_id, False):
                    points -= 1  # -1 for missed cut
        
        # Check for best overall team score
        if user_name in leaders and numeric_scores[user_name] != 0:
            points += 1  # +1 for best team score
        
        weekly_points[user_name] = points

    # Add team score row to the transposed dataframe
    transposed_df = df.set_index('User').T

    # Create a new row for team scores WITH trophy for leaders
    team_score_row = {}
    for user in users:
        user_name = user["name"]
        score_display = user_scores.get(user_name, "E")
        
        # Add trophy if this user is leading
        if user_name in leaders and score_display != "E":
            team_score_row[user_name] = f"🏆 {score_display}"
        else:
            team_score_row[user_name] = score_display

    # Insert team score row at the bottom
    team_score_df = pd.DataFrame([team_score_row], index=["Team Score"])
    transposed_with_score = pd.concat([team_score_df, transposed_df])

    # Modify cell values to add X for missed cuts (but NOT if they won tier)
    def add_missed_cut_symbol(s):
        if s.name == "Team Score":
            return s  # Don't modify team score row
        
        # First find tier leaders
        tier_scores = {}
        for user_name in s.index:
            player_name = s[user_name]
            if player_name == "🔒" or player_name not in name_to_id:
                continue
            player_id = name_to_id[player_name]
            if player_id in score_lookup:
                tier_scores[user_name] = score_lookup[player_id]
        
        best_score = min(tier_scores.values()) if tier_scores else None
        
        modified_values = []
        for user_name in s.index:
            player_name = s[user_name]
            
            if player_name == "🔒" or player_name not in name_to_id:
                modified_values.append(player_name)
                continue
            
            player_id = name_to_id[player_name]
            
            # Check if tier leader
            is_leader = (player_id in score_lookup and 
                        score_lookup[player_id] == best_score)
            
            # Check for missed cut
            is_missed_cut = cut_status.get(player_id, False)
            
            # Only add X if missed cut AND not tier leader
            if is_missed_cut and not is_leader:
                modified_values.append(f"❌ {player_name}")
            else:
                modified_values.append(player_name)
        
        return modified_values
    
    # Apply symbols to the dataframe BEFORE styling
    transposed_with_score = transposed_with_score.apply(add_missed_cut_symbol, axis=1)
    
    # Style function to bold tier leaders only (but NOT if they also missed cut)
    def highlight_tier_leaders(s):
        if s.name == "Team Score":
            return [''] * len(s)

        tier_scores = {}

        for user_name in s.index:
            player_name = str(s[user_name]).replace("❌ ", "")  # Remove X to get original name
            if player_name == "🔒" or player_name not in name_to_id:
                continue

            player_id = name_to_id[player_name]
            if player_id in score_lookup:
                tier_scores[user_name] = score_lookup[player_id]

        if not tier_scores:
            return [''] * len(s)

        best_score = min(tier_scores.values())

        styles = []
        for user_name in s.index:
            cell_value = str(s[user_name])
            player_name = cell_value.replace("❌ ", "")
            
            # Check if tier leader
            is_leader = (player_name != "🔒" and 
                        player_name in name_to_id and 
                        name_to_id[player_name] in score_lookup and 
                        score_lookup[name_to_id[player_name]] == best_score)
            
            # Check if this player also missed cut (look up in cut_status directly)
            player_missed_cut = False
            if player_name in name_to_id:
                player_id = name_to_id[player_name]
                player_missed_cut = cut_status.get(player_id, False)
            
            # Only bold if leader AND didn't miss cut
            if is_leader and not player_missed_cut:
                styles.append('font-weight: bold')
            else:
                styles.append('')
        
        return styles
    

    # Apply styling
    styled_picks_df = (transposed_with_score.style
                    .apply(highlight_tier_leaders, axis=1)
                    .set_properties(**{'text-align': 'center', 'font-size': '12px'})
                    .set_table_styles([
                        {'selector': 'th', 'props': [('font-size', '12px')]},
                        {'selector': 'th.col_heading', 'props': [('font-size', '12px')]}
                    ]))
    
    # Column config WITHOUT trophy in headers
    column_config = {}
    for user in users:
        user_name = user["name"]
        column_config[user_name] = st.column_config.TextColumn(user_name, width="small")

    column_config["Team Score"] = st.column_config.TextColumn("Team Score", width="small")
    for tier_number in range(1, 7):
        column_config[f"Tier {tier_number}"] = st.column_config.TextColumn(f"Tier {tier_number}", width="small")

# Display weekly points above the table in 4 columns (mobile-friendly)
    points_html = '<div style="display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px;">'
    
    for user in users:
        user_name = user["name"]
        pts = weekly_points.get(user_name, 0)
        
        if pts > 0:
            pts_display = f"+{pts}"
        elif pts == 0:
            pts_display = str(0)
        else:
            pts_display = str(pts)
        
        points_html += f'<div style="flex: 1 1 22%; font-size: 18px; text-align: center;"><b>{pts_display}</b></div>'
    points_html += '</div>'
    st.markdown(points_html, unsafe_allow_html=True)

    st.dataframe(
        styled_picks_df,
        width="stretch",
        height='content',
        hide_index=True,
        column_config=column_config
    )

    st.write("")

    # Get picked players for this tournament
    def get_picked_players(conn, tournament_id):
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT player_id
            FROM user_picks
            WHERE tournament_id = %s
        """, (tournament_id,))

        rows = cur.fetchall()
        player_ids = [str(row["player_id"]) for row in rows]
        return player_ids

    # Leaderboard API call and display
    try:
        from utils.leaderboard_api import get_live_leaderboard
        leaderboard = get_live_leaderboard(api_key)
        
        # Check if leaderboard is empty before filtering
        if leaderboard.empty:
            st.info("🏌️ Live leaderboard will appear once the tournament begins")
            return
            
    except Exception as e:
        st.info("🏌️ Live leaderboard will appear once the tournament begins")
        return

    picked_ids = get_picked_players(conn, tournament_id)
    leaderboard = leaderboard[leaderboard["PlayerID"].isin(picked_ids)]
    
    # Check if leaderboard is empty after filtering
    if leaderboard.empty:
        st.info("🏌️ Live leaderboard will appear once the tournament begins")
        return
    
    # Check if scores are valid (not all dashes/empty)
    valid_scores = leaderboard["Score"].apply(lambda x: x not in ["-", "", None, "nan"]).any()
    if not valid_scores:
        st.info("🏌️ Live leaderboard will appear once the tournament begins")
        return

    # Create player_id to tier lookup before dropping PlayerID
    player_tier_map = {}
    for _, row in leaderboard.iterrows():
        player_id = str(row["PlayerID"])
        cursor.execute("""
            SELECT tier_number
            FROM weekly_tiers
            WHERE tournament_id = %s AND player_id = %s
        """, (tournament_id, player_id))
        tier_result = cursor.fetchone()
        if tier_result:
            player_tier_map[row["Player"]] = tier_result["tier_number"]

    leaderboard.drop(columns=["PlayerID", "Status"], inplace=True)  # Drop Status too

    # Reset index
    df_display = leaderboard.reset_index(drop=True)
    
    tier_colors = {
        1: "#FFB3BA",  # Soft red
        2: "#D3D3D3",  # Grey
        3: "#FFFFBA",  # Soft yellow
        4: "#BAFFC9",  # Soft green
        5: "#BAE1FF",  # Soft blue
        6: "#E0BBE4"   # Soft lavender
    }

    # Apply style: tier colors, green scores, smaller font
    def highlight_by_tier(row):
        player_name = row["Player"]
        tier = player_tier_map.get(player_name)
        bg_color = tier_colors.get(tier, "")
        return [f'background-color: {bg_color}' if bg_color else '' for _ in row]

    styled_leaderboard_df = (
        df_display.style
        .apply(highlight_by_tier, axis=1)
        .set_properties(**{'text-align': 'center', 'font-size': '12px'}, subset=["Score"])
        .set_properties(**{'font-size': '12px'})
    )
    # st.write("🏌️ Live Leaderboard")
    st.dataframe(
        styled_leaderboard_df,
        width="stretch",
        height=500,
        hide_index=True
    )

    # st.write("Leaderboard will display when tournament begins")