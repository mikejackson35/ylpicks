import os
import requests
import pandas as pd
import streamlit as st

RAPIDAPI_HOST = "live-golf-data.p.rapidapi.com"
BASE_URL = "https://live-golf-data.p.rapidapi.com"


def _headers():
    return {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY"),
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



def get_live_leaderboard(org_id="1", tourn_id="003", year="2026"):
    params = {
        "orgId": org_id,
        "tournId": tourn_id,
        "year": year
    }

    leaderboard_resp = requests.get(
        f"{BASE_URL}/leaderboard",
        headers=_headers(),
        params=params
    )

    st.write("STATUS:", leaderboard_resp.status_code)
    st.write("JSON:", leaderboard_resp.json())

    # st.stop()


