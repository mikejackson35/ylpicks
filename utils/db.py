import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor


def get_connection():
    try:
        conn = psycopg2.connect(
            st.secrets["SUPABASE_DB_URL"],
            sslmode="require",
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")
        return None