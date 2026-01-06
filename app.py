import streamlit as st
import sqlite3
from datetime import datetime
import bcrypt
import streamlit_authenticator as stauth


# ----------------------------
# DATABASE SETUP
# ----------------------------
conn = sqlite3.connect("pickem.db", check_same_thread=False)
cursor = conn.cursor()

# Users table
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    name TEXT,
    password_hash TEXT
)
""")

# Picks table
cursor.execute("""
CREATE TABLE IF NOT EXISTS picks (
    username TEXT,
    game_id TEXT,
    pick TEXT,
    timestamp TEXT,
    PRIMARY KEY (username, game_id)
)
""")
conn.commit()

# ----------------------------
# SAMPLE GAMES
# ----------------------------
GAMES = [
    {"game_id": "wc1", "week": "Wild Card", "home": "Panthers", "away": "Rams", "kickoff": datetime(2026, 1, 10, 8, 0)},
    {"game_id": "wc2", "week": "Wild Card", "home": "Bears", "away": "Packers", "kickoff": datetime(2026, 1, 10, 8, 0)},
    {"game_id": "wc3", "week": "Wild Card", "home": "Jaguars", "away": "Bills", "kickoff": datetime(2026, 1, 10, 8, 0)},
    {"game_id": "wc4", "week": "Wild Card", "home": "Eagles", "away": "49ers", "kickoff": datetime(2026, 1, 11, 8, 0)},
    {"game_id": "wc5", "week": "Wild Card", "home": "Patriots", "away": "Chargers", "kickoff": datetime(2026, 1, 11, 8, 0)},
    {"game_id": "wc6", "week": "Wild Card", "home": "Steelers", "away": "Texans", "kickoff": datetime(2026, 1, 11, 8, 0)},
]

# ----------------------------
# GAME RESULTS (TEMP - MANUAL)
# ----------------------------
RESULTS = {
    "wc1": "Rams",
    "wc2": "Packers",
    "wc3": "Bills",
    "wc4": "49ers",
    "wc5": "Patriots",
    "wc6": "Steelers",
}


# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
def get_users_for_auth():
    cursor.execute("SELECT username, password_hash, name FROM users")
    rows = cursor.fetchall()
    credentials = {"usernames": {}}
    for username, pw_hash, name in rows:
        credentials["usernames"][username] = {
            "name": name,
            "password": pw_hash
        }
    return credentials

def add_test_user():
    # Add a test user if DB is empty - mj / password123
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        password_hash = bcrypt.hashpw("password123".encode(), bcrypt.gensalt()).decode()
        cursor.execute("INSERT INTO users (username, name, password_hash) VALUES (?, ?, ?)",
                       ("mj", "Mike", password_hash))
        conn.commit()


# ----------------------------
# SETUP
# ----------------------------
add_test_user()
credentials = get_users_for_auth()

authenticator = stauth.Authenticate(
    credentials=credentials,
    cookie_name="pickem_cookie",
    key="supersecretkey",
    cookie_expiry_days=30,
)

login_result = authenticator.login(location="main")
name = username = None
auth_status = False

if login_result is not None:
    name, auth_status, username = login_result


# ----------------------------
# SIGN UP (ONLY SHOWN WHEN NOT LOGGED IN)
# ----------------------------
if auth_status is None:
    with st.expander("Create a New Account"):
        new_username = st.text_input("Username")
        new_name = st.text_input("Name")
        # new_email = st.text_input("Email")
        new_pw = st.text_input("Password", type="password")
        # confirm_pw = st.text_input("Confirm Password", type="password")

        if st.button("Create Account"):
            if not all([new_username, new_name, new_pw]):
                st.error("All fields are required")
            # elif new_pw != confirm_pw:
            #     st.error("Passwords do not match")
            else:
                cursor.execute(
                    "SELECT 1 FROM users WHERE username=?",
                    (new_username,)
                )
                if cursor.fetchone():
                    st.error("Username already exists")
                else:
                    pw_hash = bcrypt.hashpw(
                        new_pw.encode(), bcrypt.gensalt()
                    ).decode()

                    cursor.execute("""
                        INSERT INTO users (username, name, password_hash)
                        VALUES (?, ?, ?)
                    """, (new_username, new_name, pw_hash))
                    conn.commit()

                    st.success("Account created! Please log in above.")


# ----------------------------
# LOGOUT / INFO
# ----------------------------
if auth_status:
    authenticator.logout("Logout", "sidebar")
    # st.sidebar.success(f"Logged in as {name}")
else:
    if auth_status is False:
        st.error("Username/password is incorrect")
    else:
        st.info("Please log in to access the app.")

# ----------------------------
# APP
# ----------------------------
if auth_status:

    # PASSWORD CHANGE
    with st.sidebar.expander("Change Password"):
        old_pw = st.text_input("Old Password", type="password")
        new_pw = st.text_input("New Password", type="password")
        confirm_pw = st.text_input("Confirm New Password", type="password")
        if st.button("Update Password"):
            cursor.execute("SELECT password_hash FROM users WHERE username=?", (username,))
            stored_hash = cursor.fetchone()[0]
            if bcrypt.checkpw(old_pw.encode(), stored_hash.encode()):
                if new_pw == confirm_pw:
                    new_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
                    cursor.execute("UPDATE users SET password_hash=? WHERE username=?", (new_hash, username))
                    conn.commit()
                    st.success("Password updated successfully!")
                else:
                    st.error("New passwords do not match")
            else:
                st.error("Old password incorrect")

    st.sidebar.divider()
    # PAGE NAVIGATION
    page = st.sidebar.radio(
        "",
        ["Leaderboard", "Weekly Grid", "Make Picks"]
    )

    if page == "Make Picks":
        st.title("🏈 Wilde NFL Pick'em 🎉")
        st.write(f"Hello **{name}**!")

        st.sidebar.divider()
        # PICK'EM LOGIC
        week = st.sidebar.selectbox("Select Round", sorted({g["week"] for g in GAMES}))
        now = datetime.utcnow()
        week_games = [g for g in GAMES if g["week"] == week]

        st.write('')

        for game in week_games:
            locked = now >= game["kickoff"]
            matchup = f'{game["away"]} @ {game["home"]}'
            st.subheader(matchup)
            st.caption(f"Kickoff: {game['kickoff']} UTC")

            cursor.execute("SELECT pick FROM picks WHERE username=? AND game_id=?", (username, game["game_id"]))
            existing = cursor.fetchone()

            if not locked:
                choice = st.radio(
                    "Pick winner",
                    [game["away"], game["home"]],
                    index=(0 if existing and existing[0] == game["home"] else 1 if existing else 0),
                    key=f"{game['game_id']}_{username}"
                )
                if st.button("Save Pick", key=f"save_{game['game_id']}"):
                    cursor.execute("INSERT OR REPLACE INTO picks (username, game_id, pick, timestamp) VALUES (?, ?, ?, ?)",
                                (username, game["game_id"], choice, now.isoformat()))
                    conn.commit()
                    st.success(f"Saved pick: {choice}")
            else:
                if existing:
                    st.info(f"Your pick: **{existing[0]}**")
                else:
                    st.warning("No pick submitted")

            # Show all picks after kickoff
            if locked:
                cursor.execute("SELECT username, pick FROM picks WHERE game_id=?", (game["game_id"],))
                st.table(cursor.fetchall())

            st.divider()

    elif page == "Weekly Grid":
        st.title("📊 Weekly Picks Grid")
        st.sidebar.divider()
        # Sidebar round selector (same pattern as Make Picks)
        week = st.sidebar.selectbox(
            "Select Round",
            sorted({g["week"] for g in GAMES})
        )

        # Games for this round
        week_games = [g for g in GAMES if g["week"] == week]
        game_ids = [g["game_id"] for g in week_games]

        if not game_ids:
            st.info("No games for this round.")
        else:
            # Fetch all picks for these games
            placeholders = ",".join("?" * len(game_ids))
            cursor.execute(
                f"""
                SELECT username, game_id, pick
                FROM picks
                WHERE game_id IN ({placeholders})
                """,
                game_ids
            )
            rows = cursor.fetchall()

            # Build grid structure
            users = sorted({r[0] for r in rows})
            grid = {user: {gid: "" for gid in game_ids} for user in users}

            for username, game_id, pick in rows:
                grid[username][game_id] = pick

            # Create display table
            table = []
            for user in users:
                row = {"User": user}
                for g in week_games:
                    row[g["game_id"]] = grid[user][g["game_id"]]
                table.append(row)

            st.dataframe(table, use_container_width=True)

    elif page == "Leaderboard":
        st.title("🏆 Playoff Leaderboard")

        # Fetch all picks
        cursor.execute(
            "SELECT username, game_id, pick FROM picks"
        )
        rows = cursor.fetchall()

        if not rows:
            st.info("No picks submitted yet.")
        else:
            scores = {}

            for username, game_id, pick in rows:
                # Skip games without results yet
                if game_id not in RESULTS:
                    continue

                if username not in scores:
                    scores[username] = 0

                if pick == RESULTS[game_id]:
                    scores[username] += 1

            if not scores:
                st.info("No completed games yet.")
            else:
                leaderboard = [
                    {"User": user, "Points": pts}
                    for user, pts in scores.items()
                ]

                leaderboard = sorted(
                    leaderboard,
                    key=lambda x: x["Points"],
                    reverse=True
                )

                st.dataframe(leaderboard, use_container_width=True)

