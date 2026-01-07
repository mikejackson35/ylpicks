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

conn.commit()

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

# Games table (source of truth)
cursor.execute("""
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    week TEXT,
    home TEXT,
    away TEXT,
    kickoff TEXT,
    winner TEXT
)
""")

conn.commit()

# ----------------------------
# SAMPLE GAMES
# ----------------------------
GAMES = [
    {"game_id": "LAR @ CAR", "week": "Wild Card", "home": "Panthers", "away": "Rams", "kickoff": datetime(2026, 1, 8, 15, 0)},
    {"game_id": "CHI @ GB", "week": "Wild Card", "home": "Bears", "away": "Packers", "kickoff": datetime(2026, 1, 8, 19, 30)},
    {"game_id": "JAX @ BUF", "week": "Wild Card", "home": "Jaguars", "away": "Bills", "kickoff": datetime(2026, 1, 8, 22, 0)},
    {"game_id": "PHI @ SF", "week": "Wild Card", "home": "Eagles", "away": "49ers", "kickoff": datetime(2026, 1, 8, 15, 0)},
    {"game_id": "NE @ LAC", "week": "Wild Card", "home": "Patriots", "away": "Chargers", "kickoff": datetime(2026, 1, 8, 19, 30)},
    {"game_id": "PIT @ HOU", "week": "Wild Card", "home": "Steelers", "away": "Texans", "kickoff": datetime(2026, 1, 8, 22, 0)},
    {"game_id": "Div1", "week": "Divisional", "home": "Team A", "away": "Team B", "kickoff": datetime(2026, 1, 17, 22, 0)},
    {"game_id": "Div2", "week": "Divisional", "home": "Team C", "away": "Team D", "kickoff": datetime(2026, 1, 17, 15, 0)},
    {"game_id": "Div3", "week": "Divisional", "home": "Team E", "away": "Team F", "kickoff": datetime(2026, 1, 18, 19, 30)},
    {"game_id": "Div4", "week": "Divisional", "home": "Team G", "away": "Team H", "kickoff": datetime(2026, 1, 18, 22, 0)},
    {"game_id": "Con1", "week": "Conference", "home": "Team A", "away": "Team B", "kickoff": datetime(2026, 1, 25, 19, 30)},
    {"game_id": "Con2", "week": "Conference", "home": "Team C", "away": "Team D", "kickoff": datetime(2026, 1, 25, 22, 0)},
    {"game_id": "SB", "week": "Superbowl", "home": "Team A", "away": "Team B", "kickoff": datetime(2026, 2, 1, 15, 0)}
]

def seed_games():
    for g in GAMES:
        cursor.execute(
            """
            INSERT OR IGNORE INTO games
            (game_id, week, home, away, kickoff)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                g["game_id"],
                g["week"],
                g["home"],
                g["away"],
                g["kickoff"].isoformat()
            )
        )
    conn.commit()


# ----------------------------
# PLAYOFF ROUND ORDER
# ----------------------------
ROUND_ORDER = [
    "Wild Card",
    "Divisional",
    "Conference",
    "Superbowl"
]

ROUND_WEIGHTS = {
    "Wild Card": 1,
    "Divisional": 2,
    "Conference": 3,
    "Superbowl": 4
}


# ----------------------------
# GAME RESULTS (TEMP - MANUAL)
# ----------------------------
# RESULTS = {
#     "LAR @ CAR": "Rams",
#     "CHI @ GB": "Packers",
#     "JAX @ BUF": "Bills",
#     "PHI @ SF": "49ers",
#     "NE @ LAC": "Patriots",
#     "PIT @ HOU": "Steelers",
# }

ADMINS = {"mj"}  # set of usernames allowed to see admin tools

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

import re

def safe_key(s: str) -> str:
    """
    Converts a string into a Streamlit-safe widget key.
    Replaces spaces with underscores, @ with 'at', and removes other special chars.
    """
    s = s.replace(' ', '_').replace('@', 'at')
    # Remove anything that is not alphanumeric or underscore
    s = re.sub(r'[^0-9a-zA-Z_]', '', s)
    return s

conn.commit()


# ----------------------------
# SETUP
# ----------------------------
add_test_user()
credentials = get_users_for_auth()

seed_games()

authenticator = stauth.Authenticate(
    credentials=credentials,
    cookie_name="pickem_cookie",
    key=st.secrets["auth_key"],
    cookie_expiry_days=30,
)

authenticator.login(location="main")

auth_status = st.session_state.get("authentication_status")
username = st.session_state.get("username")
name = st.session_state.get("name")

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
# LOGIN STATUS UI
# ----------------------------
if auth_status:
    authenticator.logout("Logout", "sidebar")
    st.sidebar.success(f"Logged in as {name}")

elif auth_status is False:
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

    if username in ADMINS:
        with st.expander("🛠 Admin: Set Game Winners"):
            cursor.execute("SELECT game_id, home, away, winner FROM games")
            games = cursor.fetchall()

            for game_id, home, away, winner in games:
                choice = st.selectbox(
                    f"{away} @ {home}",
                    ["", home, away],
                    index=(["", home, away].index(winner) if winner else 0),
                    key=f"winner_{safe_key(game_id)}"
                )

                if st.button("Save", key=f"save_winner_{safe_key(game_id)}"):
                    cursor.execute(
                        "UPDATE games SET winner=? WHERE game_id=?",
                        (choice if choice else None, game_id)
                    )
                    conn.commit()
                    st.success(f"Winner saved for {away} @ {home}")



    st.sidebar.divider()
    # PAGE NAVIGATION
    PAGES = ["Leaderboard", "Weekly Grid", "Make Picks"]
    page = st.sidebar.radio("Go to", PAGES)


    if page == "Make Picks":
        st.write(f"Hello **{name}**!")
        st.title("Make Picks Here")
        # st.write(f"Hello **{name}**!")
        st.sidebar.divider()

        # PICK'EM LOGIC
        week = st.sidebar.selectbox(
            "Select Round",
            [r for r in ROUND_ORDER if r in {g["week"] for g in GAMES}]
        )

        now = datetime.utcnow()
        week_games = [g for g in GAMES if g["week"] == week]

        st.write('')

        for game in week_games:
            locked = now >= game["kickoff"]
            matchup = f'{game["away"]} @ {game["home"]}'
            st.subheader(matchup)
            kickoff_str = game["kickoff"].strftime("%A %I:%M %p").lstrip("0")
            st.caption(f"{kickoff_str} EST")


            cursor.execute("SELECT pick FROM picks WHERE username=? AND game_id=?", (username, game["game_id"]))
            existing = cursor.fetchone()

            if not locked:
                choice = st.radio(
                    "Pick winner",
                    [game["away"], game["home"]],
                    index=(0 if existing and existing[0] == game["home"] else 1 if existing else 0),
                    key=f"{safe_key(game['game_id'])}_{safe_key(username)}"
                )
            if st.button("Save Pick", key=f"save_{safe_key(username)}_{safe_key(game['game_id'])}"):

                cursor.execute(
                    "INSERT OR REPLACE INTO picks (username, game_id, pick, timestamp) VALUES (?, ?, ?, ?)",
                    (username, game["game_id"], choice, now.isoformat())
                )
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

        # Sidebar round selector
        week = st.sidebar.selectbox(
            "Select Round",
            [r for r in ROUND_ORDER if r in {g["week"] for g in GAMES}]
        )

        week_games = [g for g in GAMES if g["week"] == week]
        game_ids = [g["game_id"] for g in week_games]

        if not game_ids:
            st.info("No games for this round.")
        else:
            # 1️⃣ Get all users and their full names
            cursor.execute("SELECT username, name FROM users")
            users = cursor.fetchall()  # list of (username, name)
            usernames = [u for u, _ in users]
            name_map = {u: n for u, n in users}

            # 2️⃣ Get picks for these games
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

            # 3️⃣ Build lookup: username -> game_id -> pick
            pick_map = {u: {gid: None for gid in game_ids} for u in usernames}
            for username, game_id, pick in rows:
                pick_map[username][game_id] = pick

            # 4️⃣ Build display table with lock logic
            now = datetime.utcnow()
            table = []
            for username, full_name in users:
                row = {"User": full_name}  # display full name

                for g in week_games:
                    locked = now >= g["kickoff"]

                    if locked:
                        row[g["game_id"]] = pick_map[username][g["game_id"]] or "—"
                    else:
                        row[g["game_id"]] = "🔒"

                table.append(row)

            # 5️⃣ Display using st.table (removes index)
            st.table(table)




    elif page == "Leaderboard":
        st.title("🏆 Leaderboard")
        st.sidebar.divider()

        # 1️⃣ Get all users (username + full name)
        cursor.execute("SELECT username, name FROM users ORDER BY name")
        users = cursor.fetchall()  # list of (username, name)

        # Mapping for easy lookup
        name_map = {username: full_name for username, full_name in users}
        usernames = [username for username, _ in users]

        # 2️⃣ Initialize points to 0 for all users
        user_points = {u: 0 for u in usernames}

        # 3️⃣ Define round weights
        ROUND_WEIGHTS = {
            "Wild Card": 1,
            "Divisional": 2,
            "Conference": 3,
            "Superbowl": 4
        }

        # 4️⃣ Get all picks
        cursor.execute("SELECT username, game_id, pick FROM picks")
        all_picks = cursor.fetchall()

        for username, game_id, pick in all_picks:
            cursor.execute("SELECT winner, week FROM games WHERE game_id=?", (game_id,))
            result = cursor.fetchone()
            if result:
                winner, week = result
                if winner and pick == winner:
                    user_points[username] += ROUND_WEIGHTS.get(week, 1)

        # 5️⃣ Build DataFrame with full names
        import pandas as pd

        df = pd.DataFrame({
            "User": [name_map.get(u, u) for u in usernames],
            "Points": [user_points[u] for u in usernames]
        })

        # 6️⃣ Sort by points descending
        df = df.sort_values("Points", ascending=False).reset_index(drop=True)

        # 7️⃣ Display in Streamlit with Points column right-aligned
        st.dataframe(
            df.style.format({"Points": "{:>d}"}),  # right-align numbers
            use_container_width=True
        )





