import streamlit as st
import json
import os
import tempfile
import time
from datetime import datetime
from contextlib import contextmanager

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "user_data.json")
LOCK_FILE = f"{DATA_FILE}.lock"
AUTO_SYNC_INTERVAL_MS = 3000

def normalize_username(username):
    """Normalize username so desktop/phone inputs map to one user."""
    if not isinstance(username, str):
        return ""
    cleaned = " ".join(username.split())
    return cleaned.casefold()

def _normalize_data(data):
    """Keep only {username: non-negative int total} entries."""
    if not isinstance(data, dict):
        return {}

    normalized = {}
    for raw_name, raw_total in data.items():
        name = normalize_username(raw_name)
        if not name:
            continue

        try:
            total = int(raw_total)
        except (TypeError, ValueError):
            continue

        # Merge legacy mixed-case keys into the same canonical user key.
        normalized[name] = normalized.get(name, 0) + max(0, total)

    return normalized

@contextmanager
def file_lock():
    """Protect read-modify-write cycles across sessions/processes."""
    if fcntl is None:
        yield
        return

    with open(LOCK_FILE, "w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)

def load_data():
    """Efficiently load user data with error handling"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding="utf-8") as f:
                return _normalize_data(json.load(f))
        return {}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}

def save_data(data):
    """Atomically save user data to reduce corruption/race issues."""
    temp_file_path = None
    safe_data = _normalize_data(data)

    try:
        data_dir = os.path.dirname(DATA_FILE)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)

        with tempfile.NamedTemporaryFile('w', delete=False, dir=data_dir or ".", encoding="utf-8") as tmp:
            json.dump(safe_data, tmp, separators=(',', ':'))
            temp_file_path = tmp.name

        os.replace(temp_file_path, DATA_FILE)
        return True
    except Exception:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return False

def ensure_user_exists(username):
    """Create user with 0 total if missing."""
    username = normalize_username(username)
    if not username:
        return False

    with file_lock():
        user_data = load_data()
        if username in user_data:
            return True

        user_data[username] = 0
        return save_data(user_data)

def update_user_total(username, delta=0, absolute_total=None):
    """Update user total using a lock-guarded read-modify-write."""
    username = normalize_username(username)
    if not username:
        return None

    with file_lock():
        user_data = load_data()
        current_total = user_data.get(username, 0)

        if absolute_total is None:
            next_total = current_total + int(delta)
        else:
            next_total = int(absolute_total)

        user_data[username] = max(0, next_total)
        if save_data(user_data):
            return user_data[username]

    return None

def initialize_session_state():
    """Initialize session state variables"""
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'current_user' not in st.session_state:
        st.session_state.current_user = ""
    if 'current_user_display' not in st.session_state:
        st.session_state.current_user_display = ""
    if 'last_update' not in st.session_state:
        st.session_state.last_update = None
    if 'confirm_reset' not in st.session_state:
        st.session_state.confirm_reset = False

def reset_user_data(username):
    """Reset user data to zero with verified persistence."""
    if update_user_total(username, absolute_total=0) is not None:
        st.session_state.last_update = datetime.now()
        return True
    return False

def run_auto_sync():
    """Keep desktop and phone sessions synced without manual refresh."""
    if st_autorefresh is not None:
        st_autorefresh(interval=AUTO_SYNC_INTERVAL_MS, key="counter_auto_sync")
        return

    # Fallback for environments where streamlit-autorefresh is unavailable.
    time.sleep(AUTO_SYNC_INTERVAL_MS / 1000)
    st.rerun()

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
        display_name = " ".join(username.split())
        username_key = normalize_username(username)
        if username_key:
            if ensure_user_exists(username_key):
                st.session_state.logged_in = True
                st.session_state.current_user = username_key
                st.session_state.current_user_display = display_name
                st.session_state.confirm_reset = False
                st.session_state.last_update = datetime.now()
                st.rerun()
            else:
                st.error("Could not save user data. Please try again.")
        else:
            st.warning("Please enter your name")

# Main Counter Interface
else:
    username = normalize_username(st.session_state.current_user)
    if username != st.session_state.current_user:
        st.session_state.current_user = username

    display_name = st.session_state.current_user_display or username
    user_data = load_data()
    current_total = user_data.get(username, 0)
    
    # Keep total prominent on small screens too.
    st.subheader(f"Hello, {display_name}!")
    st.metric("Total", f"{current_total} RMB")
    if st.button("Switch user", type="secondary", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.current_user = ""
        st.session_state.current_user_display = ""
        st.session_state.confirm_reset = False
        st.rerun()
    st.caption("Auto-sync is on (updates every 3 seconds).")
    
    st.write("---")
    
    # Quick add buttons - larger and more prominent
    st.write("### Quick Add")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("**+10**", use_container_width=True, type="primary"):
            if update_user_total(username, delta=10) is not None:
                st.session_state.last_update = datetime.now()
                st.rerun()
            else:
                st.error("Could not save your update. Please try again.")
    
    with col2:
        if st.button("**+50**", use_container_width=True, type="primary"):
            if update_user_total(username, delta=50) is not None:
                st.session_state.last_update = datetime.now()
                st.rerun()
            else:
                st.error("Could not save your update. Please try again.")
    
    with col3:
        if st.button("**+100**", use_container_width=True, type="primary"):
            if update_user_total(username, delta=100) is not None:
                st.session_state.last_update = datetime.now()
                st.rerun()
            else:
                st.error("Could not save your update. Please try again.")
    
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
            if update_user_total(username, delta=custom_amount) is not None:
                st.session_state.last_update = datetime.now()
                st.rerun()
            else:
                st.error("Could not save your update. Please try again.")
    
    # Reset section - minimal and safe
    st.write("---")
    
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
                    st.session_state.confirm_reset = False
                    st.session_state.last_update = datetime.now()
                    st.rerun()
                else:
                    st.error("Could not reset your counter. Please try again.")
        with col2:
            if st.button("Cancel", type="secondary", use_container_width=True):
                st.session_state.confirm_reset = False
                st.rerun()
    
    # Last update timestamp (subtle)
    if st.session_state.last_update:
        st.caption(f"Last update: {st.session_state.last_update.strftime('%H:%M')}")

    run_auto_sync()

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