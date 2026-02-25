import streamlit as st
import pandas as pd
from datetime import datetime, timezone
import bcrypt

from auth import init_auth, show_login, show_signup, show_logout, show_password_change
from utils.db import get_connection
from utils.leaderboard_api import get_live_leaderboard
import _pages.this_week as this_week
import _pages.make_picks as make_picks
import _pages.results as results_page

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
# FINALIZATION HELPER
# ----------------------------
from datetime import timedelta

def _parse_score(score):
    """Convert golf score string to int. Returns 999 if invalid."""
    if score == "E":
        return 0
    if isinstance(score, str):
        try:
            return int(score.replace("+", ""))
        except ValueError:
            pass
    return 999


def finalize_tournament(conn, cursor, tournament, api_key):
    """
    Score a completed tournament and write results to the DB.
    Uses tournament_player_results as a cache so the API is only hit once.
    Returns (success: bool, message: str).
    """
    tournament_id = tournament["tournament_id"]
    org_id = tournament.get("org_id") or "1"
    tourn_id = tournament.get("tourn_id")
    year = tournament.get("year") or "2026"

    if not tourn_id:
        return False, f"No tourn_id set for {tournament_id} — update tournaments_new first."

    try:
        # --- Step 1: Fetch & cache leaderboard if not already cached ---
        cursor.execute(
            "SELECT player_id, player_name, score_to_par, status FROM tournament_player_results WHERE tournament_id = %s",
            (tournament_id,)
        )
        cached_rows = cursor.fetchall()

        if not cached_rows:
            leaderboard = get_live_leaderboard(api_key, org_id, tourn_id, year)
            if leaderboard.empty:
                return False, f"API returned empty leaderboard for {tournament_id}."

            for _, lb_row in leaderboard.iterrows():
                cursor.execute("""
                    INSERT INTO tournament_player_results
                        (tournament_id, player_id, player_name, position, score_to_par, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tournament_id, player_id) DO NOTHING
                """, (
                    tournament_id,
                    str(lb_row["PlayerID"]),
                    str(lb_row["Player"]),
                    str(lb_row.get("Pos", "")),
                    str(lb_row["Score"]),
                    str(lb_row.get("Status", "active")).lower()
                ))
            conn.commit()

            cursor.execute(
                "SELECT player_id, player_name, score_to_par, status FROM tournament_player_results WHERE tournament_id = %s",
                (tournament_id,)
            )
            cached_rows = cursor.fetchall()

        # --- Step 2: Build score & cut lookups from cache ---
        score_lookup = {}
        cut_status = {}
        score_text = {}
        for row in cached_rows:
            pid = str(row["player_id"])
            score_lookup[pid] = _parse_score(row["score_to_par"])
            cut_status[pid] = (str(row["status"]).lower() == "cut")
            score_text[pid] = row["score_to_par"] or ""

        # --- Step 3: Get users and their picks ---
        cursor.execute("SELECT username FROM users")
        all_users = [r["username"] for r in cursor.fetchall()]

        cursor.execute("""
            SELECT username, tier_number, player_id
            FROM user_picks WHERE tournament_id = %s
        """, (tournament_id,))
        all_picks = cursor.fetchall()

        # --- Step 4: Find tier winners among ONLY picked players ---
        # Build tier -> set of picked player_ids
        picked_by_tier = {}
        for pick in all_picks:
            t = int(pick["tier_number"])
            pid = str(pick["player_id"])
            picked_by_tier.setdefault(t, set()).add(pid)

        tier_winners = {}
        for tier_number, picked_pids in picked_by_tier.items():
            best_score = min(
                (score_lookup.get(pid, 999) for pid in picked_pids),
                default=999
            )
            if best_score == 999:
                continue
            tier_winners[tier_number] = {
                pid for pid in picked_pids
                if score_lookup.get(pid, 999) == best_score
            }

        # --- Step 5: Calculate team scores (for best-overall bonus) ---
        user_team_scores = {}
        for uname in all_users:
            user_picks_list = [p for p in all_picks if p["username"] == uname]
            if not user_picks_list:
                user_team_scores[uname] = 999
                continue
            total = sum(
                score_lookup.get(str(p["player_id"]), 999)
                for p in user_picks_list
                if score_lookup.get(str(p["player_id"]), 999) != 999
            )
            # Only count as valid if they have at least one valid score
            has_valid = any(
                score_lookup.get(str(p["player_id"]), 999) != 999
                for p in user_picks_list
            )
            user_team_scores[uname] = total if has_valid else 999

        valid_scores = [s for s in user_team_scores.values() if s != 999]
        best_team_score = min(valid_scores) if valid_scores else 999

        # --- Step 6: Score each pick and write to tiers_results ---
        for pick in all_picks:
            uname = pick["username"]
            tier_number = int(pick["tier_number"])
            player_id = str(pick["player_id"])

            is_tier_winner = player_id in tier_winners.get(tier_number, set())
            is_missed_cut = cut_status.get(player_id, False)

            points = 0
            if is_tier_winner:
                points += 1
            if is_missed_cut:
                points -= 1

            tiers_results_id = f"{tournament_id}_{uname}_{tier_number}"
            cursor.execute("""
                INSERT INTO tiers_results
                    (tiers_results_id, tournament_id, username, tier_number,
                     player_id, points, tier_winner, missed_cut, player_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tiers_results_id) DO UPDATE SET
                    points = EXCLUDED.points,
                    tier_winner = EXCLUDED.tier_winner,
                    missed_cut = EXCLUDED.missed_cut,
                    player_score = EXCLUDED.player_score
            """, (
                tiers_results_id, tournament_id, uname, tier_number,
                player_id, points, is_tier_winner, is_missed_cut,
                score_text.get(player_id, "")
            ))

        # --- Step 7: Write weekly_results (tier points + best-overall bonus) ---
        for uname in all_users:
            cursor.execute("""
                SELECT COALESCE(SUM(points), 0) as total_points
                FROM tiers_results
                WHERE tournament_id = %s AND username = %s
            """, (tournament_id, uname))
            total_points = cursor.fetchone()["total_points"]

            if user_team_scores.get(uname, 999) == best_team_score and best_team_score != 999:
                total_points += 1

            weekly_results_id = f"{tournament_id}_{uname}"
            cursor.execute("""
                INSERT INTO weekly_results (tournament_id, username, points, weekly_results_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (weekly_results_id) DO UPDATE SET points = EXCLUDED.points
            """, (tournament_id, uname, total_points, weekly_results_id))

        # --- Step 8: Mark tournament as finalized ---
        cursor.execute("""
            UPDATE tournaments_new
            SET is_finalized = TRUE, finalized_at = NOW()
            WHERE tournament_id = %s
        """, (tournament_id,))

        conn.commit()
        return True, f"{tournament['name']} finalized successfully."

    except Exception as e:
        conn.rollback()
        return False, f"Error finalizing {tournament_id}: {e}"


# ----------------------------
# AUTO-FINALIZE COMPLETED TOURNAMENTS
# ----------------------------
now = datetime.now(timezone.utc)

cursor.execute("""
    SELECT tournament_id, name, start_time, org_id, tourn_id, year
    FROM tournaments_new
    WHERE start_time + INTERVAL '5 days' < %s
      AND is_finalized = FALSE
      AND tourn_id IS NOT NULL
    ORDER BY start_time ASC
""", (now,))

for tournament in cursor.fetchall():
    finalize_tournament(conn, cursor, tournament, st.secrets["RAPIDAPI_KEY"])

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
PAGES = ["This Week", "Make Picks", "Results"]
page = st.sidebar.radio("", PAGES)
st.sidebar.markdown("<br><br>", unsafe_allow_html=True)

# ----------------------------
# PAGE ROUTING  ← MOVED UP BEFORE LOGOUT/ADMIN
# ----------------------------
if page == "This Week":
    this_week.show(conn, cursor, st.secrets["RAPIDAPI_KEY"])

elif page == "Make Picks":
    make_picks.show(conn, cursor, username)

elif page == "Results":
    results_page.show(conn, cursor)

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
            FROM tournaments_new
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
                    FROM weekly_tiers_results
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
                        INSERT INTO weekly_tiers_results (tournament_id, tier_number, winning_player_id)
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
        conn.rollback()

        cursor.execute("""
            SELECT tournament_id, name, start_time, org_id, tourn_id, year
            FROM tournaments_new
            WHERE start_time < %s
              AND is_finalized = FALSE
              AND tourn_id IS NOT NULL
            ORDER BY start_time DESC
            LIMIT 1
        """, (datetime.now(timezone.utc),))

        tournament = cursor.fetchone()

        if not tournament:
            st.sidebar.warning("No unfinalized tournaments with a tourn_id set.")
        else:
            ok, msg = finalize_tournament(conn, cursor, tournament, st.secrets["RAPIDAPI_KEY"])
            if ok:
                st.sidebar.success(f"✅ {msg}")
                st.rerun()
            else:
                st.sidebar.error(msg)