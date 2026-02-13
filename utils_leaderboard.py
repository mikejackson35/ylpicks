import streamlit as st  # ✅ Add this import
import requests
import pandas as pd

RAPIDAPI_HOST = "live-golf-data.p.rapidapi.com"
BASE_URL = "https://live-golf-data.p.rapidapi.com"


def _headers():
    return {
        "x-rapidapi-key": st.secrets["RAPIDAPI_KEY"],  # ✅ Changed this line
        "x-rapidapi-host": RAPIDAPI_HOST
    }


def leaderboard_to_df(rows):
    return pd.DataFrame([
        {
            "PlayerID": p.get("playerId"),
            "Pos": p.get("position"),
            "Player": f"{p.get('firstName')} {p.get('lastName')}",
            "Score": p.get("total")
        }
        for p in rows
    ])


def earnings_to_df(rows):
    return pd.DataFrame([
        {
            "PlayerID": p.get("playerId"),
            "Earnings": int(p.get("earnings", {}).get("$numberInt", 0))
        }
        for p in rows
    ])


def get_live_leaderboard(api_key, org_id="1", tourn_id="005", year="2026"):
    params = {
        "orgId": org_id,
        "tournId": tourn_id,
        "year": year
    }

    leaderboard_resp = requests.get(
        f"{BASE_URL}/leaderboard",
        headers=_headers(api_key),  # ✅ Pass the key here
        params=params
    )

    data = leaderboard_resp.json()

    if "leaderboardRows" not in data:
        raise RuntimeError(f"Leaderboard API error: {data}")

    lb_df = leaderboard_to_df(data["leaderboardRows"])

    final = lb_df.reset_index(drop=True)
    return final



