import os
from datetime import datetime

import requests
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

NOTION_DATABASE_ID = "35fa6041f59c80afa912dccefcfbd26a"
NOTION_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"
AUTO_SYNC_INTERVAL_MS = 3000


def get_notion_token():
    # Prefer Streamlit secret (set as `Notion_API` in Streamlit Cloud), fall back to env var.
    try:
        token = st.secrets.get("Notion_API")
        if token:
            return token
    except Exception:
        pass
    return os.environ.get("Notion_API") or os.environ.get("NOTION_API")


def notion_headers():
    token = get_notion_token()
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def find_user_page(username):
    """Return (page_id, amount) for the user, or (None, None) if missing."""
    headers = notion_headers()
    if headers is None:
        return None, None
    payload = {
        "filter": {"property": "Name", "title": {"equals": username}},
        "page_size": 1,
    }
    resp = requests.post(
        f"{NOTION_API_BASE}/databases/{NOTION_DATABASE_ID}/query",
        headers=headers,
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None, None
    page = results[0]
    amount = page["properties"].get("Amount", {}).get("number") or 0
    return page["id"], int(amount)


def list_users():
    """Return [(name, page_id), ...] for all rows in the Counter database."""
    headers = notion_headers()
    if headers is None:
        return []
    users = []
    payload = {"page_size": 100, "sorts": [{"property": "Name", "direction": "ascending"}]}
    while True:
        resp = requests.post(
            f"{NOTION_API_BASE}/databases/{NOTION_DATABASE_ID}/query",
            headers=headers,
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for page in data.get("results", []):
            title = page["properties"].get("Name", {}).get("title", [])
            name = "".join(part.get("plain_text", "") for part in title).strip()
            if name:
                users.append((name, page["id"]))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return users


def create_user_page(username, amount=0):
    headers = notion_headers()
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": username}}]},
            "Amount": {"number": int(amount)},
        },
    }
    resp = requests.post(f"{NOTION_API_BASE}/pages", headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()["id"]


def update_page_amount(page_id, amount):
    headers = notion_headers()
    payload = {"properties": {"Amount": {"number": max(0, int(amount))}}}
    resp = requests.patch(f"{NOTION_API_BASE}/pages/{page_id}", headers=headers, json=payload, timeout=10)
    resp.raise_for_status()


def get_or_create_user(username):
    page_id, amount = find_user_page(username)
    if page_id is None:
        page_id = create_user_page(username, 0)
        amount = 0
    return page_id, amount


def apply_delta(page_id, delta=0, absolute_total=None):
    """Re-read from Notion before writing so concurrent updates from other devices don't get lost."""
    headers = notion_headers()
    resp = requests.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=headers, timeout=10)
    resp.raise_for_status()
    current = int(resp.json()["properties"].get("Amount", {}).get("number") or 0)
    next_total = current + int(delta) if absolute_total is None else int(absolute_total)
    next_total = max(0, next_total)
    update_page_amount(page_id, next_total)
    return next_total


def run_auto_sync():
    if st_autorefresh is not None:
        st_autorefresh(interval=AUTO_SYNC_INTERVAL_MS, key="counter_auto_sync")


st.set_page_config(page_title="Savings", page_icon="💸", layout="centered")

# Session defaults
st.session_state.setdefault("username", None)
st.session_state.setdefault("page_id", None)
st.session_state.setdefault("last_update", None)

if notion_headers() is None:
    st.title("💸 Savings")
    st.error(
        "Notion API token is not configured. Add `Notion_API` to Streamlit secrets "
        "(Streamlit Cloud → App settings → Secrets) or set the `Notion_API` environment variable."
    )
    st.stop()

# --- Login screen ---
if not st.session_state.username:
    st.title("💸 Savings")

    try:
        existing_users = list_users()
    except requests.RequestException as exc:
        st.error(f"Could not reach Notion: {exc}")
        st.stop()

    if existing_users:
        st.caption("Tap your name to continue.")
        # Two columns to keep buttons compact on phones.
        cols = st.columns(2)
        for idx, (name, page_id) in enumerate(existing_users):
            if cols[idx % 2].button(name, key=f"user_{page_id}", use_container_width=True):
                st.session_state.username = name
                st.session_state.page_id = page_id
                st.rerun()
        st.divider()
        st.caption("First time here? Add yourself below.")
    else:
        st.caption("No users yet — add yourself to get started.")

    with st.form("new_user_form", clear_on_submit=True):
        name = st.text_input("New username", max_chars=40, placeholder="e.g. alex")
        submitted = st.form_submit_button("Create & continue", type="primary", use_container_width=True)
    if submitted:
        clean = (name or "").strip()
        if not clean:
            st.warning("Please enter a username.")
        elif any(clean.lower() == u.lower() for u, _ in existing_users):
            st.warning("That name already exists — tap it above instead.")
        else:
            try:
                page_id, _ = get_or_create_user(clean)
                st.session_state.username = clean
                st.session_state.page_id = page_id
                st.rerun()
            except requests.HTTPError as exc:
                st.error(f"Could not reach Notion: {exc.response.status_code} {exc.response.text}")
            except requests.RequestException as exc:
                st.error(f"Could not reach Notion: {exc}")
    st.stop()

# --- Main screen ---
try:
    _, current_total = find_user_page(st.session_state.username)
    if current_total is None:
        # Row got deleted in Notion — recreate.
        st.session_state.page_id, current_total = get_or_create_user(st.session_state.username)
except requests.RequestException as exc:
    st.error(f"Sync failed: {exc}")
    st.stop()

st.title("💸 Savings")
st.caption(f"Signed in as **{st.session_state.username}**")
st.metric("Current total", f"{current_total} RMB")


def handle_change(delta=0, absolute_total=None):
    try:
        apply_delta(st.session_state.page_id, delta=delta, absolute_total=absolute_total)
        st.session_state.last_update = datetime.now()
        st.rerun()
    except requests.RequestException as exc:
        st.error(f"Could not save your update: {exc}")


st.write("#### Quick actions")
add_cols = st.columns(3)
for amount, col in zip((10, 50, 100), add_cols):
    with col:
        if st.button(f"+{amount}", type="primary", use_container_width=True, key=f"add_{amount}"):
            handle_change(delta=amount)

sub_cols = st.columns(3)
for amount, col in zip((10, 50, 100), sub_cols):
    with col:
        if st.button(f"-{amount}", use_container_width=True, key=f"sub_{amount}"):
            handle_change(delta=-amount)

with st.form("custom_form"):
    st.write("#### Custom")
    action = st.radio("Action", ["Add", "Deduct"], horizontal=True, label_visibility="collapsed")
    amount = st.number_input("Amount", min_value=1, max_value=100000, value=100, step=10)
    submitted = st.form_submit_button("Save", type="primary", use_container_width=True)
    if submitted:
        delta = int(amount) if action == "Add" else -int(amount)
        handle_change(delta=delta)

if st.button("Reset to zero", use_container_width=True):
    handle_change(absolute_total=0)

if st.button("Sign out", use_container_width=True):
    st.session_state.username = None
    st.session_state.page_id = None
    st.rerun()

st.caption("Synced with Notion — auto-refreshes every 3 seconds.")
if st.session_state.last_update:
    st.caption(f"Last update: {st.session_state.last_update.strftime('%H:%M:%S')}")

run_auto_sync()

st.markdown(
    """
<style>
.block-container {padding-top: 3rem; padding-bottom: 2rem; max-width: 520px;}
.stMetric {border: 1px solid #E6E6E6; border-radius: 14px; padding: 0.35rem;}
.stButton button {border-radius: 10px; border: 1px solid #E5E7EB;}
</style>
""",
    unsafe_allow_html=True,
)
