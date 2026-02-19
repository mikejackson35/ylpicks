import streamlit as st
import pandas as pd
from datetime import datetime, timezone
import bcrypt

from auth import init_auth, show_login, show_signup, show_logout, show_password_change
from utils.db import get_connection
from utils.leaderboard_api import get_live_leaderboard
import _pages.this_week as this_week
import _pages.make_picks as make_picks

# ----------------------------
# CSS STYLES
# ----------------------------
st.markdown("""
<style>
/* Sidebar radio labels */
section[data-testid="stSidebar"] label {
    font-size: 40px !important;
    font-weight: 700 !important;
}

/* Make the actual radio circles slightly bigger */
section[data-testid="stSidebar"] input[type="radio"] {
    transform: scale(1.3);
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
[data-testid="stDataFrameToolbar"],
[data-testid="stElementToolbar"] {
    display: none;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
.block-container {
    padding-top: 0.25rem;
}
</style>
""", unsafe_allow_html=True)


st.markdown("""
<style>
[data-testid="stToolbar"] {
    display: none;
}
</style>
""", unsafe_allow_html=True)




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
# SEASON STANDINGS IN SIDEBAR
# ----------------------------
cursor.execute("""
    SELECT username, SUM(points) as total_points
    FROM weekly_results
    GROUP BY username
""")
results = cursor.fetchall()

# Get all users (in case some don't have any weekly_results yet)
cursor.execute("SELECT username, name FROM users ORDER BY name")
all_users = cursor.fetchall()
user_name_map = {u["username"]: u["name"] for u in all_users}

# Build points dictionary
user_points = {u["username"]: 0 for u in all_users}
for result in results:
    user_points[result["username"]] = result["total_points"] or 0

# Build dataframe
sb_df = pd.DataFrame({
    "Name": [user_name_map[username] for username in user_points.keys()],
    "Points": list(user_points.values())
}).sort_values("Points", ascending=False).reset_index(drop=True)

html = """
<style>
.lb-row {
    display: flex;
    justify-content: space-between;
    padding: 3px 6px;
    border-bottom: 1px solid #444;
}
.lb-name {
    text-align: left;
}
.lb-points {
    font-weight: bold;
}
</style>
<div style="text-align:center;">
<b>Season</b><br><br>
"""

for _, row in sb_df.iterrows():
    html += f"""
<div class="lb-row">
    <div class="lb-name">{row['Name']}</div>
    <div class="lb-points">{row['Points']}</div>
</div>
"""

html += "</div>"

st.sidebar.markdown(html, unsafe_allow_html=True)


st.sidebar.markdown("<br>", unsafe_allow_html=True)
with st.sidebar.expander("Scoring Rules"):
    st.markdown("""
    EACH WEEK \n
    Tier Winner:   +1pt  
    Lowest Team:   +1pt  
    Missed Cut:   -1pt
    \n
    $100 to the winner after TOUR Championship
    (from mj)  
    """, text_alignment='center')


st.sidebar.markdown("<br>", unsafe_allow_html=True)

# ----------------------------
# PAGE NAVIGATION
# ----------------------------
PAGES = ["This Week", "Make Picks"]
page = st.sidebar.radio("", PAGES)
st.sidebar.markdown("<br><br>", unsafe_allow_html=True)

# ----------------------------
# PAGE ROUTING  ← MOVED UP BEFORE LOGOUT/ADMIN
# ----------------------------
if page == "This Week":
    this_week.show(conn, cursor, st.secrets["RAPIDAPI_KEY"])

elif page == "Make Picks":
    make_picks.show(conn, cursor, username)

# ----------------------------
# LOGOUT / PASSWORD
# ----------------------------
st.sidebar.markdown("<br>", unsafe_allow_html=True)
show_logout(conn)
show_password_change(cursor, conn, username)

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
                    FROM weekly_tiers t
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