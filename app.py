import streamlit as st
import pandas as pd
from datetime import datetime, timezone
import re
import bcrypt

from auth import init_auth, show_login, show_signup, show_logout, show_password_change
from utils.db import get_connection
from utils.leaderboard_api import get_live_leaderboard
import _pages.this_week as this_week
import _pages.make_picks as make_picks

# ----------------------------
# Database Connection
# ----------------------------
conn = get_connection()
if conn is None:
    st.stop()
cursor = conn.cursor()

# ----------------------------
# ADMINS
# ----------------------------
ADMINS = {"mj"}

# ----------------------------
# ADD TEST USER
# ----------------------------
def add_test_user():
    cursor.execute("SELECT 1 FROM users WHERE username = %s", ("mj",))
    if cursor.fetchone() is None:
        password = "password123"
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cursor.execute(
            "INSERT INTO users (username, name, password_hash) VALUES (%s, %s, %s)",
            ("mj", "Mike", password_hash)
        )
        conn.commit()

add_test_user()

# ----------------------------
# AUTHENTICATION
# ----------------------------
init_auth()

auth_status = st.session_state["authentication_status"]
username = st.session_state["username"]
name = st.session_state["name"]

if auth_status is not True:
    show_login(cursor)
    show_signup(cursor, conn)
    st.stop()

# ----------------------------
# LOGGED IN - SHOW APP
# ----------------------------
show_logout(conn)
show_password_change(cursor, conn, username)

# ----------------------------
# SEASON STANDINGS HEADER
# ----------------------------
cursor.execute("SELECT username, name FROM users ORDER BY name")
sb_users = cursor.fetchall()
sb_name_map = {user["username"]: user["name"] for user in sb_users}
sb_usernames = [user["username"] for user in sb_users]
sb_user_points = {u: 0 for u in sb_usernames}

cursor.execute("SELECT username, tournament_id, tier_number, player_id FROM picks")
sb_all_picks = cursor.fetchall()

cursor.execute("SELECT DISTINCT tournament_id FROM results")
sb_completed_tournaments = [row["tournament_id"] for row in cursor.fetchall()]

for sb_tournament_id in sb_completed_tournaments:
    cursor.execute("SELECT start_time FROM tournaments WHERE tournament_id=%s", (sb_tournament_id,))
    sb_tournament_info = cursor.fetchone()
    sb_start_time = sb_tournament_info["start_time"] if sb_tournament_info else None
    now = datetime.now(timezone.utc)

    if sb_start_time and now < sb_start_time:
        continue

    try:
        sb_leaderboard = get_live_leaderboard(st.secrets["RAPIDAPI_KEY"])
        sb_score_lookup = {}
        for _, lb_row in sb_leaderboard.iterrows():
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
            sb_score_lookup[player_id] = numeric_score
    except:
        sb_score_lookup = {}

    sb_tournament_scores = {}
    for sb_username in sb_usernames:
        total_score = 0
        user_picks = [p for p in sb_all_picks
                     if p["username"] == sb_username and p["tournament_id"] == sb_tournament_id]

        for pick in user_picks:
            tier_number = pick["tier_number"]
            player_id = str(pick["player_id"])

            cursor.execute("""
                SELECT winning_player_id
                FROM results
                WHERE tournament_id=%s AND tier_number=%s
            """, (sb_tournament_id, tier_number))
            result = cursor.fetchone()

            if result and str(result["winning_player_id"]) == player_id:
                sb_user_points[sb_username] += 1

            if player_id in sb_score_lookup:
                total_score += sb_score_lookup[player_id]

        sb_tournament_scores[sb_username] = total_score

    if sb_tournament_scores:
        sb_best_score = min(sb_tournament_scores.values())
        for sb_username, score in sb_tournament_scores.items():
            if score == sb_best_score:
                sb_user_points[sb_username] += 1

sb_df = pd.DataFrame({
    "Name": [sb_name_map.get(u, u) for u in sb_usernames],
    "Points": [sb_user_points[u] for u in sb_usernames]
}).sort_values("Points", ascending=False).reset_index(drop=True)

# Display standings as markdown header
standings_parts = []
for _, row in sb_df.iterrows():
    standings_parts.append(f"**{row['Name']}** {row['Points']}")

standings_str = "&nbsp;&nbsp;&nbsp;".join(standings_parts)
st.markdown(f"<p style='font-size:14px'>{standings_str}</p>", unsafe_allow_html=True)
st.divider()

# ----------------------------
# ADMIN TOOLS
# ----------------------------
if username in ADMINS:
    with st.sidebar.expander("🛠 Admin: Set Tier Winners"):

        cursor.execute("""
            SELECT tournament_id, name
            FROM tournaments
            ORDER BY start_time
        """)
        tournaments = cursor.fetchall()

        if not tournaments:
            st.info("No tournaments found")
        else:
            tournament_map = {t["name"]: t["tournament_id"] for t in tournaments}
            selected_name = st.selectbox("Tournament", list(tournament_map.keys()))
            tournament_id = tournament_map[selected_name]

            for tier_number in range(1, 6):
                st.markdown(f"**Tier {tier_number} Winner**")

                cursor.execute("""
                    SELECT p.player_id, p.name
                    FROM tiers t
                    JOIN players p ON p.player_id = t.player_id
                    WHERE t.tournament_id = %s
                    AND t.tier_number = %s
                """, (tournament_id, tier_number))
                players = cursor.fetchall()

                if not players:
                    st.info("No players assigned to this tier")
                    continue

                player_options = {p["name"]: p["player_id"] for p in players}

                cursor.execute("""
                    SELECT winning_player_id
                    FROM results
                    WHERE tournament_id=%s AND tier_number=%s
                """, (tournament_id, tier_number))
                existing = cursor.fetchone()

                existing_name = None
                if existing:
                    for pname, pid in player_options.items():
                        if pid == existing["winning_player_id"]:
                            existing_name = pname

                choice = st.selectbox(
                    f"Winner (Tier {tier_number})",
                    [""] + list(player_options.keys()),
                    index=(list(player_options.keys()).index(existing_name) + 1)
                    if existing_name else 0,
                    key=f"tier_win_{tournament_id}_{tier_number}"
                )

                if st.button("Save", key=f"save_{tournament_id}_{tier_number}"):
                    cursor.execute("""
                        INSERT INTO results (tournament_id, tier_number, winning_player_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (tournament_id, tier_number)
                        DO UPDATE SET winning_player_id=EXCLUDED.winning_player_id
                    """, (
                        tournament_id,
                        tier_number,
                        player_options.get(choice)
                    ))
                    conn.commit()
                    st.success("Saved")
                    st.rerun()

st.sidebar.divider()

# ----------------------------
# SEASON LEADERBOARD IN SIDEBAR
# ----------------------------
st.sidebar.markdown("**Season Leaderboard**")

cursor.execute("SELECT username, name FROM users ORDER BY name")
sb_users = cursor.fetchall()
sb_name_map = {user["username"]: user["name"] for user in sb_users}
sb_usernames = [user["username"] for user in sb_users]

sb_user_points = {u: 0 for u in sb_usernames}

cursor.execute("""
    SELECT username, tournament_id, tier_number, player_id
    FROM picks
""")
sb_all_picks = cursor.fetchall()

cursor.execute("""
    SELECT DISTINCT tournament_id 
    FROM results
""")
sb_completed_tournaments = [row["tournament_id"] for row in cursor.fetchall()]

for sb_tournament_id in sb_completed_tournaments:
    cursor.execute("SELECT start_time FROM tournaments WHERE tournament_id=%s", (sb_tournament_id,))
    sb_tournament_info = cursor.fetchone()
    sb_start_time = sb_tournament_info["start_time"] if sb_tournament_info else None
    now = datetime.now(timezone.utc)

    if sb_start_time and now < sb_start_time:
        continue

    try:
        sb_leaderboard = get_live_leaderboard(st.secrets["RAPIDAPI_KEY"])
        sb_score_lookup = {}

        for _, lb_row in sb_leaderboard.iterrows():
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
            sb_score_lookup[player_id] = numeric_score
    except:
        sb_score_lookup = {}

    sb_tournament_scores = {}

    for sb_username in sb_usernames:
        total_score = 0
        user_picks = [p for p in sb_all_picks
                     if p["username"] == sb_username and p["tournament_id"] == sb_tournament_id]

        for pick in user_picks:
            tier_number = pick["tier_number"]
            player_id = str(pick["player_id"])

            cursor.execute("""
                SELECT winning_player_id
                FROM results
                WHERE tournament_id=%s AND tier_number=%s
            """, (sb_tournament_id, tier_number))
            result = cursor.fetchone()

            if result and str(result["winning_player_id"]) == player_id:
                sb_user_points[sb_username] += 1

            if player_id in sb_score_lookup:
                total_score += sb_score_lookup[player_id]

        sb_tournament_scores[sb_username] = total_score

    if sb_tournament_scores:
        sb_best_score = min(sb_tournament_scores.values())
        for sb_username, score in sb_tournament_scores.items():
            if score == sb_best_score:
                sb_user_points[sb_username] += 1

sb_df = pd.DataFrame({
    "Name": [sb_name_map.get(u, u) for u in sb_usernames],
    "Points": [sb_user_points[u] for u in sb_usernames]
})
sb_df = sb_df.sort_values("Points", ascending=False).reset_index(drop=True)

st.sidebar.dataframe(
    sb_df,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Points": st.column_config.NumberColumn("Points", width='small')
    }
)

st.sidebar.divider()

# ----------------------------
# PAGE NAVIGATION
# ----------------------------
PAGES = ["This Week", "Make Picks"]
page = st.sidebar.radio("Go to", PAGES)

# ----------------------------
# PAGE ROUTING
# ----------------------------
if page == "This Week":
    this_week.show(conn, cursor, st.secrets["RAPIDAPI_KEY"])

elif page == "Make Picks":
    make_picks.show(conn, cursor, username)