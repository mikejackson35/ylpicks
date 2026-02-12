import os
import requests
import pandas as pd

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


def get_live_leaderboard(org_id="1", tourn_id="005", year="2026"):
    params = {
        "orgId": org_id,
        "tournId": tourn_id,
        "year": year
    }

    # ---- leaderboard ----
    leaderboard_resp = requests.get(
        f"{BASE_URL}/leaderboard",
        headers=_headers(),
        params=params
    )

    data = leaderboard_resp.json()

    if "leaderboardRows" not in data:
        raise RuntimeError(f"Leaderboard API error: {data}")

    lb_df = leaderboard_to_df(data["leaderboardRows"])

    # ---- earnings ----
    earnings_resp = requests.get(
        f"{BASE_URL}/earnings",
        headers=_headers(),
        params=params
    )

    edata = earnings_resp.json()

    if "leaderboard" not in edata:
        raise RuntimeError(f"Earnings API error: {edata}")

    earnings_df = earnings_to_df(edata["leaderboard"])

    # ---- merge ----
    final = (
        lb_df
        .merge(earnings_df, on="PlayerID", how="left")
        .fillna({"Earnings": 0})
        .drop(columns="PlayerID")
        .reset_index(drop=True)
    )

    return final



