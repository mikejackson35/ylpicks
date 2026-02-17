import streamlit as st
import bcrypt
from streamlit_cookies_controller import CookieController

controller = CookieController()


def init_auth():
    """Check cookies and initialize session state"""
    if "authentication_status" not in st.session_state:
        saved_username = controller.get("username")
        if saved_username:
            st.session_state["authentication_status"] = True
            st.session_state["username"] = saved_username
            st.session_state["name"] = controller.get("name")
        else:
            st.session_state["authentication_status"] = None
            st.session_state["username"] = None
            st.session_state["name"] = None


def show_login(cursor):
    """Show login form"""
    st.title("Login")
    
    with st.form("login_form"):
        login_username = st.text_input("Username")
        login_password = st.text_input("Password", type="password")
        remember_me = st.checkbox("Stay logged in", value=True)
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
                    
                    if remember_me:
                        controller.set("username", user["username"])
                        controller.set("name", user["name"])
                    
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.session_state["authentication_status"] = False
                    st.error("Username/password is incorrect")
            else:
                st.error("Please enter both username and password")


def show_signup(cursor, conn):
    """Show signup form"""
    with st.expander("Create a New Account"):
        new_username = st.text_input("Username")
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


def show_logout(conn):
    """Show logout button in sidebar"""
    with st.sidebar:
        st.success(f"Logged in as {st.session_state['name']}")
        if st.button("Logout", key="main_logout"):
            st.session_state["authentication_status"] = None
            st.session_state["username"] = None
            st.session_state["name"] = None
            
            controller.remove("username")
            controller.remove("name")
            
            st.rerun()


def show_password_change(cursor, conn, username):
    """Show password change form in sidebar"""
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