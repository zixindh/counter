import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime

import streamlit as st

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "user_data.json")
LOCK_FILE = f"{DATA_FILE}.lock"
AUTO_SYNC_INTERVAL_MS = 3000
DEFAULT_USER = "me"


@contextmanager
def file_lock():
    if fcntl is None:
        yield
        return

    with open(LOCK_FILE, "w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)


def load_total():
    """Load just one running total for quick personal use."""
    try:
        if not os.path.exists(DATA_FILE):
            return 0
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if isinstance(raw, dict):
            # Backward compatibility with older multi-user format.
            return max(0, int(raw.get(DEFAULT_USER, 0)))
        return max(0, int(raw))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0


def save_total(total):
    temp_file_path = None
    safe_total = max(0, int(total))

    try:
        with tempfile.NamedTemporaryFile("w", delete=False, dir=BASE_DIR, encoding="utf-8") as tmp:
            json.dump(safe_total, tmp)
            temp_file_path = tmp.name
        os.replace(temp_file_path, DATA_FILE)
        return True
    except Exception:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return False


def apply_delta(delta=0, absolute_total=None):
    with file_lock():
        current = load_total()
        next_total = current + int(delta) if absolute_total is None else int(absolute_total)
        next_total = max(0, next_total)
        if save_total(next_total):
            return next_total
    return None


def run_auto_sync():
    if st_autorefresh is not None:
        st_autorefresh(interval=AUTO_SYNC_INTERVAL_MS, key="counter_auto_sync")
        return
    time.sleep(AUTO_SYNC_INTERVAL_MS / 1000)
    st.rerun()


if "last_update" not in st.session_state:
    st.session_state.last_update = None

st.set_page_config(page_title="Savings", page_icon="💸", layout="centered")
st.title("💸 Savings")
st.caption("Quickly add or deduct money.")

current_total = load_total()
st.metric("Current total", f"{current_total} RMB")

st.write("#### Quick actions")
add_cols = st.columns(3)
for amount, col in zip((10, 50, 100), add_cols):
    with col:
        if st.button(f"+{amount}", type="primary", use_container_width=True):
            if apply_delta(delta=amount) is not None:
                st.session_state.last_update = datetime.now()
                st.rerun()

sub_cols = st.columns(3)
for amount, col in zip((10, 50, 100), sub_cols):
    with col:
        if st.button(f"-{amount}", use_container_width=True):
            if apply_delta(delta=-amount) is not None:
                st.session_state.last_update = datetime.now()
                st.rerun()

with st.form("custom_form"):
    st.write("#### Custom")
    action = st.radio("Action", ["Add", "Deduct"], horizontal=True, label_visibility="collapsed")
    amount = st.number_input("Amount", min_value=1, max_value=100000, value=100, step=10)
    submitted = st.form_submit_button("Save", type="primary", use_container_width=True)

    if submitted:
        delta = int(amount) if action == "Add" else -int(amount)
        if apply_delta(delta=delta) is not None:
            st.session_state.last_update = datetime.now()
            st.rerun()
        else:
            st.error("Could not save your update. Please try again.")

if st.button("Reset to zero", use_container_width=True):
    if apply_delta(absolute_total=0) is not None:
        st.session_state.last_update = datetime.now()
        st.rerun()

st.caption("Auto-sync every 3 seconds.")
if st.session_state.last_update:
    st.caption(f"Last update: {st.session_state.last_update.strftime('%H:%M')}")

run_auto_sync()

st.markdown(
    """
<style>
.block-container {padding-top: 1rem; padding-bottom: 2rem; max-width: 520px;}
.stMetric {border: 1px solid #E6E6E6; border-radius: 14px; padding: 0.35rem;}
.stButton button {border-radius: 10px; border: 1px solid #E5E7EB;}
</style>
""",
    unsafe_allow_html=True,
)
