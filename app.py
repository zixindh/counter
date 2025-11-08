import streamlit as st
import json
import os
from datetime import datetime

# Configuration
DATA_FILE = "user_data.json"

def load_data():
    """Efficiently load user data with error handling"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        return {}
    except (json.JSONDecodeError, Exception):
        return {}

def save_data(data):
    """Efficiently save user data"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, separators=(',', ':'))
        return True
    except Exception:
        return False

def initialize_session_state():
    """Initialize session state variables"""
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'current_user' not in st.session_state:
        st.session_state.current_user = ""
    if 'last_update' not in st.session_state:
        st.session_state.last_update = None

def reset_user_data(username):
    """Reset user data to zero"""
    user_data = load_data()
    if username in user_data:
        user_data[username] = 0
        save_data(user_data)
        st.session_state.last_update = datetime.now()
        return True
    return False

# Load existing data
user_data = load_data()
initialize_session_state()

# App UI
st.set_page_config(page_title="RMB Counter", page_icon="💰", layout="centered")

st.title("💰 RMB Counter")

# User Login Section
if not st.session_state.logged_in:
    st.subheader("Enter your name")

    with st.form("login_form"):
        username = st.text_input(
            "Your name",
            placeholder="Type your name here...",
            label_visibility="collapsed",
            key="login_username",
        )
        login_submitted = st.form_submit_button("Start counting", type="primary", use_container_width=True)

    if login_submitted:
        username = username.strip()
        if username:
            st.session_state.logged_in = True
            st.session_state.current_user = username
            st.session_state.last_update = datetime.now()

            # Initialize new user with 0 if doesn't exist
            if username not in user_data:
                user_data[username] = 0
                save_data(user_data)
            st.rerun()
        else:
            st.warning("Please enter your name")

# Main Counter Interface
else:
    username = st.session_state.current_user
    current_total = user_data.get(username, 0)
    
    # User info header with auto-logout
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.subheader(f"Hello, {username}!")
    with col2:
        st.metric("Total", f"{current_total} RMB")
    with col3:
        if st.button("Switch user", type="secondary", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.current_user = ""
            st.rerun()
    
    st.write("---")
    
    # Quick add buttons - larger and more prominent
    st.write("### Quick Add")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("**+10**", use_container_width=True, type="primary"):
            user_data[username] = current_total + 10
            if save_data(user_data):
                st.session_state.last_update = datetime.now()
                st.rerun()
    
    with col2:
        if st.button("**+50**", use_container_width=True, type="primary"):
            user_data[username] = current_total + 50
            if save_data(user_data):
                st.session_state.last_update = datetime.now()
                st.rerun()
    
    with col3:
        if st.button("**+100**", use_container_width=True, type="primary"):
            user_data[username] = current_total + 100
            if save_data(user_data):
                st.session_state.last_update = datetime.now()
                st.rerun()
    
    # Custom amount section
    st.write("---")
    st.write("### Custom Amount")
    
    with st.form("custom_amount_form"):
        col1, col2 = st.columns([3, 1])
        with col1:
            custom_amount = st.number_input(
                "Enter amount", 
                min_value=1, 
                max_value=10000, 
                value=100,
                step=10,
                label_visibility="collapsed"
            )
        with col2:
            add_custom = st.form_submit_button("Add", type="primary", use_container_width=True)
            
        if add_custom:
            user_data[username] = current_total + custom_amount
            if save_data(user_data):
                st.session_state.last_update = datetime.now()
                st.rerun()
    
    # Reset section - minimal and safe
    st.write("---")
    
    if 'confirm_reset' not in st.session_state:
        st.session_state.confirm_reset = False
    
    if not st.session_state.confirm_reset:
        if st.button("Reset counter to zero", type="secondary", use_container_width=True):
            st.session_state.confirm_reset = True
            st.rerun()
    else:
        st.warning("Reset your counter to zero?")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Yes, reset", type="primary", use_container_width=True):
                if reset_user_data(username):
                    user_data[username] = 0
                    st.session_state.confirm_reset = False
                    st.session_state.last_update = datetime.now()
                    st.rerun()
        with col2:
            if st.button("Cancel", type="secondary", use_container_width=True):
                st.session_state.confirm_reset = False
                st.rerun()
    
    # Last update timestamp (subtle)
    if st.session_state.last_update:
        st.caption(f"Last update: {st.session_state.last_update.strftime('%H:%M')}")

# Add some minimal styling
st.markdown("""
<style>
    .stButton button {
        transition: all 0.3s ease;
    }
    .stButton button:hover {
        transform: translateY(-2px);
    }
</style>
""", unsafe_allow_html=True)