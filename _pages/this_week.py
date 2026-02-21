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
    st.subheader(tournament["name"])
    
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

    # Insert team score row at the top
    team_score_df = pd.DataFrame([team_score_row], index=["Team Score"])
    transposed_with_score = pd.concat([team_score_df, transposed_df])

    # Style function to highlight tier leaders (green) and missed cuts (red)
    def highlight_tier_leaders(s):
        if s.name == "Team Score":
            return [''] * len(s)

        tier_scores = {}

        for user_name in s.index:
            player_name = s[user_name]
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
            player_name = s[user_name]
            
            # Check if tier leader (green has priority)
            is_leader = (player_name != "🔒" and 
                        player_name in name_to_id and 
                        name_to_id[player_name] in score_lookup and 
                        score_lookup[name_to_id[player_name]] == best_score)
            
            if is_leader:
                styles.append('background-color: #c9f7d3')  # Green for leader
            elif player_name in name_to_id:
                # Check for missed cut (red)
                player_id = name_to_id[player_name]
                if cut_status.get(player_id, False):
                    styles.append('background-color: #ffcccc')  # Light red for missed cut
                else:
                    styles.append('')
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

    st.dataframe(
        styled_picks_df,
        width="stretch",
        height='content',
        hide_index=True,
        column_config=column_config
    )

    st.write("")
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

    # Define light colors for each tier
    # tier_colors = {
    #     1: "#FFE6E6",  # Light red
    #     2: "#FFF4E6",  # Light orange
    #     3: "#FFFBE6",  # Light yellow
    #     4: "#E6F7FF",  # Light blue
    #     5: "#F0E6FF",  # Light purple
    #     6: "#E6FFE6"   # Light green
    # }
    
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
        # .applymap(
        #     lambda x: "color: green" if isinstance(x, str) and x.startswith("-") else "",
        #     subset=["Score"]
        # )
        .set_properties(**{'text-align': 'center', 'font-size': '12px'}, subset=["Score"])
        .set_properties(**{'font-size': '12px'})
    )
    st.write("🏌️ Live Leaderboard")
    st.dataframe(
        styled_leaderboard_df,
        width="stretch",
        height=500,
        hide_index=True
    )

    # st.write("Leaderboard will display when tournament begins")