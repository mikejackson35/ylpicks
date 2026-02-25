import streamlit as st
import pandas as pd


def show(conn, cursor):

    st.subheader("Past Results")
    st.write(" ")

    # Get all finalized tournaments, most recent first
    cursor.execute("""
        SELECT tournament_id, name, start_time
        FROM tournaments
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
        FROM tournament_scores
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

        with st.expander(f"**{tname}**"):#  —  {summary}"):

            # Pull pick_scores for this tournament
            cursor.execute("""
                SELECT
                    tr.username,
                    tr.tier_number,
                    p.name AS player_name,
                    tr.player_score,
                    tr.tier_winner,
                    tr.missed_cut,
                    tr.points
                FROM pick_scores tr
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
            style_rows = []
            for tier_num in tiers:
                row_data = {}
                style_data = {}
                for uname in usernames:
                    col = name_map[uname]
                    pick = tier_data[tier_num].get(uname)
                    if not pick:
                        row_data[col] = ""
                        style_data[col] = ""
                        continue

                    player = pick["player_name"]
                    winner = pick["tier_winner"]
                    cut = pick["missed_cut"]

                    row_data[col] = player.split()[-1] if player else "?"
                    if winner and not cut:
                        style_data[col] = "background-color: #d4edda"
                    elif cut and not winner:
                        style_data[col] = "background-color: #f8d7da"
                    else:
                        style_data[col] = ""

                table_rows.append(row_data)
                style_rows.append(style_data)

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
            team_style = {}
            for uname in usernames:
                col = name_map[uname]
                total = user_team_totals.get(uname)
                if total is None:
                    team_row[col] = "-"
                    team_style[col] = ""
                else:
                    sign = "+" if total > 0 else ""
                    team_row[col] = f"{sign}{total}"
                    team_style[col] = "background-color: #d4edda" if total == best_total else ""

            table_rows.append(team_row)
            style_rows.append(team_style)

            points_html = '<div style="display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px;">'
            for uname in usernames:
                pts = weekly_map.get((tid, uname))
                if pts is None:
                    pts_display = "-"
                elif pts > 0:
                    pts_display = f"+{pts}"
                else:
                    pts_display = str(pts)
                points_html += f'<div style="flex: 1 1 22%; font-size: 18px; text-align: left; text-indent: 10px;"><b>{pts_display}</b></div>'
            points_html += '</div>'
            st.markdown(points_html, unsafe_allow_html=True)
            st.write("")

            df = pd.DataFrame(table_rows)
            style_df = pd.DataFrame(style_rows, columns=df.columns)
            styled = df.style.apply(lambda _: style_df, axis=None)
            column_config = {
                name_map[u]: st.column_config.TextColumn(name_map[u], width="small")
                for u in usernames
            }
            column_config["Team Score"] = st.column_config.TextColumn("Team Score", width="small")
            for tier_number in range(1, 7):
                column_config[f"Tier {tier_number}"] = st.column_config.TextColumn(f"Tier {tier_number}", width="small")
            st.dataframe(styled, hide_index=True, column_config=column_config, use_container_width=True)
