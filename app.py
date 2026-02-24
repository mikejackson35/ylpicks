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

/* --- Fix top spacing (prevents title from clipping) --- */
.block-container {
    padding-top: 2.5rem;
}

/* --- Hide GitHub / Fork everywhere (desktop + mobile) --- */
[data-testid="stAppViewContainer"] a[href*="github.com"] {
    display: none !important;
}

/* --- Hide Share + Deploy buttons --- */
header button[aria-label="Share"],
header button[aria-label="Deploy"] {
    display: none !important;
}
            
/* ---------- Remove DataFrame Hover Toolbars ---------- */
[data-testid="stDataFrameToolbar"],
[data-testid="stElementToolbar"] {
    display: none !important;
}

/* --- Hide footer --- */
footer {
    visibility: hidden;
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
# AUTO-FINALIZE COMPLETED TOURNAMENTS
# ----------------------------
from datetime import timedelta

# Get tournaments that ended (start_time + 4 days 20 hours) but haven't been finalized
tournament_end_offset = timedelta(days=0, hours=1)
now = datetime.now(timezone.utc)

cursor.execute("""
    SELECT t.tournament_id, t.name, t.start_time
    FROM tournaments t
    WHERE NOT EXISTS (
        SELECT 1 FROM results r 
        WHERE r.tournament_id = t.tournament_id 
        LIMIT 1
    )
""")

all_tournaments = cursor.fetchall()
unfinalized_tournaments = [
    t for t in all_tournaments 
    if t["start_time"] + tournament_end_offset < now
]

for tournament in unfinalized_tournaments:
    tournament_id = tournament["tournament_id"]
    
    try:
        # Fetch final leaderboard
        from utils.leaderboard_api import get_live_leaderboard
        leaderboard = get_live_leaderboard(st.secrets["RAPIDAPI_KEY"])
        
        if leaderboard.empty:
            continue
        
        # Create score lookup
        score_lookup = {}
        cut_status = {}
        for _, lb_row in leaderboard.iterrows():
            player_id = str(lb_row["PlayerID"])
            score = lb_row["Score"]
            status = str(lb_row.get("Status", "active")).lower()
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
        
        # Calculate tier winners for each tier (1-5)
        for tier_number in range(1, 6):
            # Get all players in this tier
            cursor.execute("""
                SELECT player_id
                FROM weekly_tiers
                WHERE tournament_id = %s AND tier_number = %s
            """, (tournament_id, tier_number))
            tier_players = cursor.fetchall()
            
            if not tier_players:
                continue
            
            # Find the best score in this tier
            best_score = 999
            winning_player_id = None
            
            for player in tier_players:
                player_id = str(player["player_id"])
                if player_id in score_lookup:
                    if score_lookup[player_id] < best_score:
                        best_score = score_lookup[player_id]
                        winning_player_id = player_id
            
            # Insert tier winner into results
            if winning_player_id:
                cursor.execute("""
                    INSERT INTO results (tournament_id, tier_number, winning_player_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (tournament_id, tier_number)
                    DO UPDATE SET winning_player_id = EXCLUDED.winning_player_id
                            """, (tournament_id, tier_number, winning_player_id))
        
        # Now calculate weekly points for each user
        cursor.execute("SELECT username, name FROM users")
        all_users = cursor.fetchall()
        
        cursor.execute("""
            SELECT username, tier_number, player_id
            FROM user_picks
            WHERE tournament_id = %s
        """, (tournament_id,))
        all_picks = cursor.fetchall()
        
        pick_map = {u["username"]: {tier: None for tier in range(1, 6)} for u in all_users}
        for row in all_picks:
            pick_map[row["username"]][row["tier_number"]] = row["player_id"]
        
        # Calculate team scores for "best overall" award
        user_team_scores = {}
        for user in all_users:
            username = user["username"]
            total_score = 0
            for tier_number in range(1, 6):
                pick_id = pick_map[username][tier_number]
                if pick_id and str(pick_id) in score_lookup:
                    total_score += score_lookup[str(pick_id)]
            user_team_scores[username] = total_score
        
        best_team_score = min(user_team_scores.values()) if user_team_scores else 999
        
        # Calculate points for each user
        for user in all_users:
            username = user["username"]
            points = 0
            
            # Count tier wins
            for tier_number in range(1, 7):
                pick_id = pick_map[username][tier_number]
                if pick_id and str(pick_id) in score_lookup:
                    player_id = str(pick_id)
                    
                    # Check if this pick won the tier
                    cursor.execute("""
                        SELECT winning_player_id
                        FROM results
                        WHERE tournament_id = %s AND tier_number = %s
                    """, (tournament_id, tier_number))
                    result = cursor.fetchone()
                    
                    if result and str(result["winning_player_id"]) == player_id:
                        points += 1  # +1 for tier win
                    
                    # Check for missed cut
                    if cut_status.get(player_id, False):
                        points -= 1  # -1 for missed cut
            
            # Check for best overall team score
            if user_team_scores[username] == best_team_score and best_team_score != 999:
                points += 1  # +1 for best team score
            
            # Insert into weekly_results
            weekly_results_id = f"{tournament_id}_{username}"
            cursor.execute("""
                INSERT INTO weekly_results (tournament_id, username, points, weekly_results_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (weekly_results_id)
                DO UPDATE SET points = EXCLUDED.points
            """, (tournament_id, username, points, weekly_results_id))
        
        conn.commit()
        
    except Exception as e:
            # Silently continue if API fails or other errors
            conn.rollback()  # Add this line to clear the failed transaction
            continue

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
    border-bottom: .1px solid #B7CCBE;
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
with st.sidebar.expander("Scoring"):
    st.markdown("""
    **Week** <br>
    +1pt Tier Winner <br>
    +1pt Team Score <br>
    -1pt Missed Cut <br>
    \n
    **Season** <br>
    $100 to winner \n
    <small>NOTE: must play all weeks to qualify </small> 😭😭😭😭
    """, unsafe_allow_html=True)# text_alignment='center')


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

            for tier_number in range(1, 7):
                st.markdown(f"**Tier {tier_number} Winner**")

                cursor.execute("""
                    SELECT p.player_id, p.name
                    FROM weekly_tiers t
                    JOIN players p ON CAST(p.player_id AS TEXT) = CAST(t.player_id AS TEXT)
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
                        if str(pid) == str(existing["winning_player_id"]):
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

    # Manual finalize button - OUTSIDE the expander
    if st.sidebar.button("🔄 Finalize Last Tournament", key="manual_finalize"):
        # Get most recently ended tournament that hasn't been finalized
        cursor.execute("""
            SELECT t.tournament_id, t.name, t.start_time
            FROM tournaments t
            WHERE t.start_time < %s
            AND NOT EXISTS (
                SELECT 1 FROM results r 
                WHERE r.tournament_id = t.tournament_id 
                LIMIT 1
            )
            ORDER BY t.start_time DESC
            LIMIT 1
        """, (datetime.now(timezone.utc),))
        
        tournament = cursor.fetchone()
        
        if not tournament:
            st.sidebar.warning("No tournaments to finalize")
        else:
            tournament_id = tournament["tournament_id"]
            tournament_name = tournament["name"]
            
            try:
                # Fetch final leaderboard
                from utils.leaderboard_api import get_live_leaderboard
                leaderboard = get_live_leaderboard(st.secrets["RAPIDAPI_KEY"])
                
                if leaderboard.empty:
                    st.sidebar.error("Could not fetch leaderboard")
                else:
                    # Create score lookup
                    score_lookup = {}
                    cut_status = {}
                    for _, lb_row in leaderboard.iterrows():
                        player_id = str(lb_row["PlayerID"])
                        score = lb_row["Score"]
                        status = str(lb_row.get("Status", "active")).lower()
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
                    
                    # Calculate tier winners for each tier (1-6)
                    for tier_number in range(1, 7):
                        cursor.execute("""
                            SELECT player_id
                            FROM weekly_tiers
                            WHERE tournament_id = %s AND tier_number = %s
                        """, (tournament_id, tier_number))
                        tier_players = cursor.fetchall()
                        
                        if not tier_players:
                            continue
                        
                        best_score = 999
                        winning_player_id = None
                        
                        for player in tier_players:
                            player_id = str(player["player_id"])
                            if player_id in score_lookup:
                                if score_lookup[player_id] < best_score:
                                    best_score = score_lookup[player_id]
                                    winning_player_id = player_id
                        
                        if winning_player_id:
                            cursor.execute("""
                                INSERT INTO results (tournament_id, tier_number, winning_player_id)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (tournament_id, tier_number)
                                DO UPDATE SET winning_player_id = EXCLUDED.winning_player_id
                            """, (tournament_id, tier_number, winning_player_id))
                    
                    # Calculate weekly points
                    cursor.execute("SELECT username, name FROM users")
                    all_users = cursor.fetchall()
                    
                    cursor.execute("""
                        SELECT username, tier_number, player_id
                        FROM user_picks
                        WHERE tournament_id = %s
                    """, (tournament_id,))
                    all_picks = cursor.fetchall()
                    
                    pick_map = {u["username"]: {tier: None for tier in range(1, 7)} for u in all_users}
                    for row in all_picks:
                        pick_map[row["username"]][row["tier_number"]] = row["player_id"]
                    
                    # Calculate team scores
                    user_team_scores = {}
                    for user in all_users:
                        username_key = user["username"]
                        total_score = 0
                        for tier_number in range(1, 7):
                            pick_id = pick_map[username_key][tier_number]
                            if pick_id and str(pick_id) in score_lookup:
                                total_score += score_lookup[str(pick_id)]
                        user_team_scores[username_key] = total_score
                    
                    best_team_score = min(user_team_scores.values()) if user_team_scores else 999
                    
                    # Calculate points
                    for user in all_users:
                        username_key = user["username"]
                        points = 0
                        
                        for tier_number in range(1, 7):
                            pick_id = pick_map[username_key][tier_number]
                            if pick_id and str(pick_id) in score_lookup:
                                player_id = str(pick_id)
                                
                                cursor.execute("""
                                    SELECT winning_player_id
                                    FROM results
                                    WHERE tournament_id = %s AND tier_number = %s
                                """, (tournament_id, tier_number))
                                result = cursor.fetchone()
                                
                                if result and str(result["winning_player_id"]) == player_id:
                                    points += 1
                                
                                if cut_status.get(player_id, False):
                                    points -= 1
                        
                        if user_team_scores[username_key] == best_team_score and best_team_score != 999:
                            points += 1
                        
                        weekly_results_id = f"{tournament_id}_{username_key}"
                        cursor.execute("""
                            INSERT INTO weekly_results (tournament_id, username, points, weekly_results_id)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (weekly_results_id)
                            DO UPDATE SET points = EXCLUDED.points
                        """, (tournament_id, username_key, points, weekly_results_id))
                    
                    conn.commit()
                    st.sidebar.success(f"✅ {tournament_name} finalized!")
                    st.rerun()
                    
            except Exception as e:
                st.sidebar.error(f"Error: {e}")