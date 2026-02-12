import streamlit as st
from utils_leaderboard import get_live_leaderboard

from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt

from datetime import datetime, timezone

import os
import re


# ----------------------------
# Database Connection
# ----------------------------
def get_connection():
    try:
        conn = psycopg2.connect(
            st.secrets["SUPABASE_DB_URL"],  # must be your full Supabase URI
            sslmode="require",
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")
        return None

# Try to connect
conn = get_connection()
if conn is None:
    st.stop()  # Stop the app if DB connection fails
cursor = conn.cursor()


# ----------------------------
# ADMINS
# ----------------------------
ADMINS = {"mj"}  # set of usernames allowed to see admin tools


# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
def safe_key(s: str) -> str:
    """Convert string to Streamlit-safe widget key"""
    s = s.replace(" ", "_").replace("@", "at")
    return re.sub(r"[^0-9a-zA-Z_]", "", s)

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
# AUTHENTICATION (Manual with bcrypt)
# ----------------------------

if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None
    st.session_state["username"] = None
    st.session_state["name"] = None

auth_status = st.session_state["authentication_status"]
username = st.session_state["username"]
name = st.session_state["name"]

# Manual Login Form
if auth_status is not True:
    st.title("Login")
    
    with st.form("login_form"):
        login_username = st.text_input("Username")
        # login_username = login_username.strip().lower()
        login_password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
            if login_username and login_password:
                cursor.execute(
                    "SELECT username, name, password_hash FROM users WHERE username=%s",
                    (login_username,)
                )
                user = cursor.fetchone()
                
                if user and bcrypt.checkpw(login_password.encode(), user["password_hash"].encode()):
                    st.session_state["authentication_status"] = True
                    st.session_state["username"] = user["username"]
                    st.session_state["name"] = user["name"]
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.session_state["authentication_status"] = False
                    st.error("Username/password is incorrect")
            else:
                st.error("Please enter both username and password")

# ----------------------------
# SIGN UP (ONLY SHOWN WHEN NOT LOGGED IN)
# ----------------------------
if not auth_status:
    with st.expander("Create a New Account"):
        new_username = st.text_input("Username")
        # new_username = new_username.strip().lower()
        new_name = st.text_input("Name")
        new_pw = st.text_input("Password", type="password")

        if st.button("Create Account"):
            if not all([new_username, new_name, new_pw]):
                st.error("All fields are required")
            else:
                cursor.execute(
                    "SELECT 1 FROM users WHERE username=%s",
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
                        VALUES (%s, %s, %s)
                    """, (new_username, new_name, pw_hash))
                    conn.commit()

                    st.success("Account created! Please log in above.")
                    st.rerun()

# ----------------------------
# LOGOUT
# ----------------------------
if auth_status:
    with st.sidebar:
        st.success(f"Logged in as {name}")
#         if st.button("Logout"):
#             st.session_state["authentication_status"] = None
#             st.session_state["username"] = None
#             st.session_state["name"] = None
#             st.rerun()


# ----------------------------
# APP
# ----------------------------
if auth_status:

    # PASSWORD CHANGE
    with st.sidebar.expander("Change Password"):
        old_pw = st.text_input("Old Password", type="password", key="old_pw")
        new_pw = st.text_input("New Password", type="password", key="new_pw")
        confirm_pw = st.text_input("Confirm New Password", type="password", key="confirm_pw")
        if st.button("Update Password"):
            if not all([old_pw, new_pw, confirm_pw]):
                st.error("All fields are required")
            else:
                cursor.execute("SELECT password_hash FROM users WHERE username=%s", (username,))
                result = cursor.fetchone()
                if result:
                    stored_hash = result["password_hash"]
                    if bcrypt.checkpw(old_pw.encode(), stored_hash.encode()):
                        if new_pw == confirm_pw:
                            new_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
                            cursor.execute("UPDATE users SET password_hash=%s WHERE username=%s", (new_hash, username))
                            conn.commit()
                            st.success("Password updated successfully!")
                            st.rerun()
                        else:
                            st.error("New passwords do not match")
                    else:
                        st.error("Old password incorrect")
                else:
                    st.error("User not found")

    # st.sidebar.divider()

    # ----------------------------
    # ADMIN TOOLS
    # ----------------------------
    if auth_status and username in ADMINS:

        with st.sidebar.expander("🛠 Admin: Set Tier Winners"):

            # Select tournament
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

                # For each tier
                for tier_number in range(1, 6):

                    st.markdown(f"**Tier {tier_number} Winner**")

                    # Players in this tier
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

                    # Existing result
                    cursor.execute("""
                        SELECT winning_player_id
                        FROM results
                        WHERE tournament_id=%s AND tier_number=%s
                    """, (tournament_id, tier_number))
                    existing = cursor.fetchone()

                    existing_name = None
                    if existing:
                        for name, pid in player_options.items():
                            if pid == existing["winning_player_id"]:
                                existing_name = name

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

    # PAGE NAVIGATION
    PAGES = ["Leaderboard", "All Picks", "Make Picks"]
    page = st.sidebar.radio("Go to", PAGES)


    if page == "Make Picks":
        col1, space, col2 = st.columns([2.25, .25, 2.50])
        with col1:
            st.title("Make Picks")
        with col2:
            # Select tournament
            cursor.execute("SELECT tournament_id, name, start_time FROM tournaments ORDER BY start_time")
            tournaments = cursor.fetchall()
            if not tournaments:
                st.warning("No tournaments available")
            else:
                tournament_map = {t["name"]: t["tournament_id"] for t in tournaments}
                selected_name = st.selectbox("Tournament", list(tournament_map.keys()))
                tournament_id = tournament_map[selected_name]

        st.sidebar.divider()

        # Current time (UTC)
        from datetime import timezone
        now = datetime.now(timezone.utc)

        # Get tournament start time to lock picks
        cursor.execute("SELECT start_time FROM tournaments WHERE tournament_id=%s", (tournament_id,))
        tournament_info = cursor.fetchone()
        start_time = tournament_info["start_time"] if tournament_info else None
        locked = start_time and now >= start_time

        st.write("")

        # For each tier (1–5)
        for tier_number in range(1, 6):
            st.subheader(f"Tier {tier_number}")

            # Get players for this tier
            cursor.execute("""
                SELECT p.player_id, p.name
                FROM tiers t
                JOIN players p ON p.player_id = t.player_id
                WHERE t.tournament_id=%s AND t.tier_number=%s
            """, (tournament_id, tier_number))
            players = cursor.fetchall()
            if not players:
                st.info("No players assigned to this tier")
                continue

            # Get existing pick for this user/tier
            cursor.execute("""
                SELECT player_id FROM picks
                WHERE username=%s AND tournament_id=%s AND tier_number=%s
            """, (username, tournament_id, tier_number))
            existing = cursor.fetchone()
            existing_pick = existing["player_id"] if existing else None

            # Options
            player_options = {p["name"]: p["player_id"] for p in players}

            if not locked:
                choice_name = None
                # If existing pick exists, get name
                for name, pid in player_options.items():
                    if pid == existing_pick:
                        choice_name = name

                choice_name = st.selectbox(
                    "Select Player",
                    [""] + list(player_options.keys()),
                    index=(list(player_options.keys()).index(choice_name)+1 if choice_name else 0),
                    key=f"pick_{tournament_id}_tier{tier_number}_{safe_key(username)}"
                )

                if st.button("Save", key=f"save_{tournament_id}_tier{tier_number}_{safe_key(username)}"):
                    # Delete old pick
                    cursor.execute("""
                        DELETE FROM picks
                        WHERE username=%s AND tournament_id=%s AND tier_number=%s
                    """, (username, tournament_id, tier_number))
                    # Insert new pick
                    cursor.execute("""
                        INSERT INTO picks (username, tournament_id, tier_number, player_id, timestamp)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (username, tournament_id, tier_number, player_options.get(choice_name), now.isoformat()))
                    conn.commit()
                    st.success(f"Saved pick: {choice_name}")
                    st.rerun()
            else:
                if existing_pick:
                    # Display name for locked pick
                    locked_name = next((name for name, pid in player_options.items() if pid == existing_pick), "Unknown")
                    st.info(f"Your locked pick: **{locked_name}**")
                else:
                    st.warning("No pick submitted")


    elif page == "All Picks":
        col1, space, col2 = st.columns([2.25, .25, 2.50])
        with col1:
            st.title("All Picks")
        with col2:
            # Select tournament
            cursor.execute("SELECT tournament_id, name, start_time FROM tournaments ORDER BY start_time")
            tournaments = cursor.fetchall()
            if not tournaments:
                st.warning("No tournaments available")
            else:
                tournament_map = {t["name"]: t["tournament_id"] for t in tournaments}
                selected_name = st.selectbox("Tournament", list(tournament_map.keys()))
                tournament_id = tournament_map[selected_name]

        st.sidebar.divider()
        st.write("")

        # Get current time
        from datetime import datetime, timezone
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
        # When building table
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

        # 5️⃣ Display as DataFrame
        import pandas as pd
        df = pd.DataFrame(table)

        column_config = {"User": st.column_config.TextColumn("User", width="content")}
        for tier_number in range(1, 6):
            column_config[f"Tier {tier_number}"] = st.column_config.TextColumn(f"Tier {tier_number}", width="content")

        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config=column_config,
            row_height=50
        )

    elif page == "Leaderboard":
        st.title("Overall")
        st.sidebar.divider()

        # 1️⃣ Get all users
        cursor.execute("SELECT username, name FROM users ORDER BY name")
        users = cursor.fetchall()
        name_map = {user["username"]: user["name"] for user in users}
        usernames = [user["username"] for user in users]

        # 2️⃣ Initialize points
        user_points = {u: 0 for u in usernames}

        # 3️⃣ Optional: define tier weights (if you want tier 1 to be worth more)
        TIER_WEIGHTS = {1: 5, 2: 4, 3: 3, 4: 2, 5: 1}  # example, 5 points for tier 1, etc.

        # 4️⃣ Get all picks
        cursor.execute("""
            SELECT username, tournament_id, tier_number, player_id
            FROM picks
        """)
        all_picks = cursor.fetchall()
        # 5️⃣ Compare picks to results
        for pick in all_picks:
            username = pick["username"]
            tournament_id = pick["tournament_id"]
            tier_number = pick["tier_number"]
            player_id = pick["player_id"]

            # Get tournament start time
            cursor.execute("SELECT start_time FROM tournaments WHERE tournament_id=%s", (tournament_id,))
            tournament_info = cursor.fetchone()
            start_time = tournament_info["start_time"] if tournament_info else None
            now = datetime.now(timezone.utc)

            if start_time and now < start_time:
                continue  # skip tournaments that haven't started yet

            # Get the winning player for this tier
            cursor.execute("""
                SELECT winning_player_id
                FROM results
                WHERE tournament_id=%s AND tier_number=%s
            """, (tournament_id, tier_number))
            result = cursor.fetchone()

            if result and result["winning_player_id"] == player_id:
                user_points[username] += TIER_WEIGHTS.get(tier_number, 1)


        # 6️⃣ Build DataFrame with full names
        import pandas as pd
        df = pd.DataFrame({
            "Name": [name_map.get(u, u) for u in usernames],
            "Points": [user_points[u] for u in usernames]
        }).rename(columns={"Points": "Earnings"})

        # 7️⃣ Sort descending
        df = df.sort_values("Earnings", ascending=False).reset_index(drop=True)

        df["Earnings"] = df["Earnings"].map("${:,.0f}".format)

        column_config = {
            # "Name": st.column_config.TextColumn("Name", width='large'),
            "Earnings": st.column_config.NumberColumn("Earnings", width='content')
        }

        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config=column_config
        )

        st.write("")
        st.title("This Week")

        # make filter for only picked players in this tournament
        import pandas as pd


        def get_picked_players(conn):
            query = """
                SELECT DISTINCT player_id
                FROM picks
            """

            df = pd.read_sql(query, conn)

            # Convert to string to match RapidAPI IDs
            return df["player_id"].astype(str).tolist()



        # make leaderboard API call and display
        try:
            leaderboard= get_live_leaderboard()
        except Exception as e:
            st.error(f"Leaderboard will show when tournament starts... maybe ...  {e}")
            st.stop()

        picked_ids = get_picked_players(conn)

        leaderboard = leaderboard[leaderboard["PlayerID"].isin(picked_ids)]

        # Format earnings as currency
        leaderboard["Earnings"] = leaderboard["Earnings"].map("${:,.0f}".format)

        leaderboard.drop(columns=["PlayerID"], inplace=True)

        # Reset index to remove index column in display
        df_display = leaderboard.reset_index(drop=True)

        # Apply style: green color for negative scores (under par)
        styled_df = (
            df_display.style
            .applymap(
                lambda x: "color: green" if isinstance(x, str) and x.startswith("-") else "",
                subset=["Score"]
            )
            # Center align Score and Earnings columns
            .set_properties(**{'text-align': 'center'}, subset=["Score", "Earnings"])
        )

        # Show in Streamlit
        st.dataframe(
            styled_df,
            use_container_width=True,
            height=500,
            hide_index=True
        )





# ----------------------------
# LOGOUT
# ----------------------------
if auth_status is True:
    with st.sidebar:
        # st.success(f"Logged in as {name}")
        if st.button("Logout"):
            st.session_state["authentication_status"] = None
            st.session_state["username"] = None
            st.session_state["name"] = None
            st.rerun()