import streamlit as st
import pandas as pd
from datetime import datetime, timezone


def show(conn, cursor, api_key):

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
    st.write("")

    # Get current time
    now = datetime.now(timezone.utc)

    # Get tournament start time
    cursor.execute("SELECT start_time FROM tournaments WHERE tournament_id=%s", (tournament_id,))
    tournament_info = cursor.fetchone()
    start_time = tournament_info["start_time"] if tournament_info else None
    now = datetime.now(timezone.utc)
    locked = start_time and now < start_time  # locked = True if tournament hasn't started

    # 1️⃣ Get all users
    cursor.execute("SELECT username, name FROM users")
    users = cursor.fetchall()
    usernames = [u["username"] for u in users]
    name_map = {u["username"]: u["name"] for u in users}

    # 2️⃣ Get picks for this tournament
    cursor.execute("""
        SELECT username, tier_number, player_id
        FROM picks
        WHERE tournament_id=%s
    """, (tournament_id,))
    rows = cursor.fetchall()

    # 3️⃣ Build lookup: username -> tier_number -> player_id
    pick_map = {u: {tier: None for tier in range(1, 6)} for u in usernames}
    for row in rows:
        pick_map[row["username"]][row["tier_number"]] = row["player_id"]

    # 4️⃣ Build display table
    table = []
    for user in users:
        username = user["username"]
        row_data = {"User": user["name"]}

        for tier_number in range(1, 6):
            pick_id = pick_map[username][tier_number]

            if pick_id and not locked:
                # Show pick if tournament started
                cursor.execute("SELECT name_last FROM players WHERE player_id=%s", (pick_id,))
                player = cursor.fetchone()
                pick_name = player["name_last"] if player else "Unknown"
                row_data[f"Tier {tier_number}"] = pick_name
            else:
                # Tournament not started or pick not made
                row_data[f"Tier {tier_number}"] = "🔒"

        table.append(row_data)

    # 5️⃣ Build DataFrame
    df = pd.DataFrame(table)

    # Get leaderboard to highlight leaders in each tier
    try:
        from utils.leaderboard_api import get_live_leaderboard
        leaderboard_for_highlight = get_live_leaderboard(api_key)

        # Create score lookup: player_id -> numeric_score
        score_lookup = {}
        for _, lb_row in leaderboard_for_highlight.iterrows():
            player_id = str(lb_row["PlayerID"])
            score = lb_row["Score"]
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
            for tier_num in range(1, 6):
                pick_id = pick_map[username][tier_num]
                if pick_id:
                    cursor.execute("SELECT name_last FROM players WHERE player_id=%s", (pick_id,))
                    player = cursor.fetchone()
                    if player:
                        name_to_id[player["name_last"]] = str(pick_id)

    except Exception as e:
        score_lookup = {}
        name_to_id = {}

    # Calculate cumulative scores for each user
    user_scores = {}
    numeric_scores = {}

    for user in users:
        username = user["username"]
        user_name = user["name"]
        total_score = 0

        for tier_number in range(1, 6):
            pick_id = pick_map[username][tier_number]
            if pick_id and str(pick_id) in score_lookup:
                total_score += score_lookup[str(pick_id)]

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

    # Create a new row for team scores
    team_score_row = {}
    for user in users:
        user_name = user["name"]
        team_score_row[user_name] = user_scores.get(user_name, "E")

    # Insert team score row at the top
    team_score_df = pd.DataFrame([team_score_row], index=["Team Score"])
    transposed_with_score = pd.concat([team_score_df, transposed_df])

    # Style function to highlight tier leaders
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

        return ['background-color: #c9f7d3' if (s[user_name] != "🔒" and
                s[user_name] in name_to_id and
                name_to_id[s[user_name]] in score_lookup and
                score_lookup[name_to_id[s[user_name]]] == best_score)
                else '' for user_name in s.index]

    # Apply styling
    styled_picks_df = (transposed_with_score.style
                    .apply(highlight_tier_leaders, axis=1)
                    .set_properties(**{'text-align': 'center', 'font-size': '12px'})
                    .set_table_styles([
                        {'selector': 'th', 'props': [('font-size', '12px')]},
                        {'selector': 'th.col_heading', 'props': [('font-size', '12px')]}
                    ]))

    # Column config with trophy for leaders
    column_config = {}
    for user in users:
        user_name = user["name"]

        if user_name in leaders and user_scores.get(user_name, "E") != "E":
            header_text = f"🏆 {user_name}"
        else:
            header_text = user_name

        column_config[user_name] = st.column_config.TextColumn(header_text, width="content")

    column_config["Team Score"] = st.column_config.TextColumn("Team Score", width="content")
    for tier_number in range(1, 6):
        column_config[f"Tier {tier_number}"] = st.column_config.TextColumn(f"Tier {tier_number}", width="content")

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
            FROM picks
            WHERE tournament_id = %s
        """, (tournament_id,))

        rows = cur.fetchall()
        player_ids = [str(row["player_id"]) for row in rows]
        return player_ids

    # Leaderboard API call and display
    try:
        from utils.leaderboard_api import get_live_leaderboard
        leaderboard = get_live_leaderboard(api_key)
    except Exception as e:
        st.error(f"Leaderboard will show when tournament starts... maybe ... {e}")
        return

    picked_ids = get_picked_players(conn, tournament_id)
    leaderboard = leaderboard[leaderboard["PlayerID"].isin(picked_ids)]

    # Create player_id to tier lookup before dropping PlayerID
    player_tier_map = {}
    for _, row in leaderboard.iterrows():
        player_id = str(row["PlayerID"])
        cursor.execute("""
            SELECT tier_number
            FROM tiers
            WHERE tournament_id = %s AND player_id = %s
        """, (tournament_id, player_id))
        tier_result = cursor.fetchone()
        if tier_result:
            player_tier_map[row["Player"]] = tier_result["tier_number"]

    leaderboard.drop(columns=["PlayerID"], inplace=True)

    # Reset index
    df_display = leaderboard.reset_index(drop=True)

    # Define light colors for each tier
    tier_colors = {
        1: "#FFE6E6",  # Light red
        2: "#FFF4E6",  # Light orange
        3: "#FFFBE6",  # Light yellow
        4: "#E6F7FF",  # Light blue
        5: "#F0E6FF"   # Light purple
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
        .applymap(
            lambda x: "color: green" if isinstance(x, str) and x.startswith("-") else "",
            subset=["Score"]
        )
        .set_properties(**{'text-align': 'center', 'font-size': '12px'}, subset=["Score"])
        .set_properties(**{'font-size': '12px'})
    )

    st.dataframe(
        styled_leaderboard_df,
        width="stretch",
        height=500,
        hide_index=True
    )