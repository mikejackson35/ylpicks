import streamlit as st
import pandas as pd


def show(conn, cursor):

    st.title("Past Results")
    st.write(" ")

    # Get all finalized tournaments, most recent first
    cursor.execute("""
        SELECT tournament_id, name, start_time
        FROM tournaments_new
        WHERE is_finalized = TRUE
        ORDER BY start_time DESC
    """)
    tournaments = cursor.fetchall()

    if not tournaments:
        st.info("No completed tournaments yet.")
        return

    # Get all users (for consistent column ordering)
    cursor.execute("SELECT username, name FROM users ORDER BY name")
    users = cursor.fetchall()
    usernames = [u["username"] for u in users]
    name_map = {u["username"]: u["name"] for u in users}

    # Weekly totals for all users across all finalized tournaments
    cursor.execute("""
        SELECT tournament_id, username, points
        FROM weekly_results
        WHERE tournament_id = ANY(%s)
    """, ([t["tournament_id"] for t in tournaments],))
    weekly_rows = cursor.fetchall()
    weekly_map = {}
    for row in weekly_rows:
        weekly_map[(row["tournament_id"], row["username"])] = row["points"]

    for tournament in tournaments:
        tid = tournament["tournament_id"]
        tname = tournament["name"]

        # Build summary line: "Name +N, Name +N, ..."
        scores = []
        for uname in usernames:
            pts = weekly_map.get((tid, uname))
            if pts is not None:
                sign = "+" if pts >= 0 else ""
                scores.append(f"{name_map[uname]} {sign}{pts}")
        summary = "  |  ".join(scores)

        with st.expander(f"**{tname}**  —  {summary}"):

            # Pull tiers_results for this tournament
            cursor.execute("""
                SELECT
                    tr.username,
                    tr.tier_number,
                    p.name AS player_name,
                    tr.player_score,
                    tr.tier_winner,
                    tr.missed_cut,
                    tr.points
                FROM tiers_results tr
                JOIN players p ON CAST(p.player_id AS TEXT) = tr.player_id
                WHERE tr.tournament_id = %s
                ORDER BY tr.tier_number, tr.username
            """, (tid,))
            pick_rows = cursor.fetchall()

            if not pick_rows:
                st.write("No pick data available.")
                continue

            # Build: tier_number -> {username -> row}
            tier_data = {}
            for row in pick_rows:
                t = row["tier_number"]
                u = row["username"]
                tier_data.setdefault(t, {})[u] = row

            tiers = sorted(tier_data.keys())

            # One row per tier, one column per user
            table_rows = []
            for tier_num in tiers:
                row_data = {}
                for uname in usernames:
                    pick = tier_data[tier_num].get(uname)
                    if not pick:
                        row_data[name_map[uname]] = ""
                        continue

                    player = pick["player_name"]
                    winner = pick["tier_winner"]
                    cut = pick["missed_cut"]

                    last_name = player.split()[-1] if player else "?"
                    if winner and not cut:
                        badge = " 🏆"
                    elif winner and cut:
                        badge = " 🏆✂️"
                    elif cut:
                        badge = " ✂️"
                    else:
                        badge = ""

                    row_data[name_map[uname]] = f"{last_name}{badge}"

                table_rows.append(row_data)

            # Build team score row from pick_rows
            def parse_score(s):
                if s == "E": return 0
                try: return int(str(s).replace("+", ""))
                except: return None

            user_team_totals = {}
            for uname in usernames:
                scores = [
                    parse_score(r["player_score"])
                    for r in pick_rows
                    if r["username"] == uname
                ]
                valid = [s for s in scores if s is not None]
                user_team_totals[uname] = sum(valid) if valid else None

            valid_totals = [v for v in user_team_totals.values() if v is not None]
            best_total = min(valid_totals) if valid_totals else None

            team_row = {}
            for uname in usernames:
                total = user_team_totals.get(uname)
                if total is None:
                    team_row[name_map[uname]] = "-"
                else:
                    sign = "+" if total > 0 else ""
                    trophy = " 🏆" if total == best_total else ""
                    team_row[name_map[uname]] = f"{sign}{total}{trophy}"

            table_rows.append(team_row)

            df = pd.DataFrame(table_rows)
            st.dataframe(df, hide_index=True, use_container_width=True)

            # st.markdown(
            #     "  |  ".join(
            #         f"**{name_map[u]}**: {'+' if (weekly_map.get((tid,u)) or 0) >= 0 else ''}{weekly_map.get((tid,u), '-')}"
            #         for u in usernames
            #     )
            # )
