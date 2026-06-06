import os
import threading
import time
from datetime import datetime

import requests
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

st.set_page_config(page_title="Savings", page_icon="💸", layout="centered")

NOTION_DATABASE_ID = "35fa6041f59c80afa912dccefcfbd26a"
NOTION_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"
AUTO_SYNC_INTERVAL_MS = 15000


class LatestAmountSyncer:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = {}
        self.workers = set()
        self.errors = {}
        self.saved_at = {}

    def queue(self, page_id, amount, headers):
        start_worker = False
        with self.lock:
            self.pending[page_id] = {
                "amount": int(amount),
                "headers": dict(headers),
                "changed_at": time.monotonic(),
            }
            self.errors.pop(page_id, None)
            if page_id not in self.workers:
                self.workers.add(page_id)
                start_worker = True

        if start_worker:
            thread = threading.Thread(target=self._write_latest, args=(page_id,), daemon=True)
            thread.start()

    def has_pending(self, page_id):
        with self.lock:
            return page_id in self.pending

    def status(self, page_id):
        with self.lock:
            return self.errors.get(page_id), self.saved_at.get(page_id)

    def _write_latest(self, page_id):
        while True:
            time.sleep(0.35)
            with self.lock:
                pending = self.pending.get(page_id)
                if pending is None:
                    self.workers.discard(page_id)
                    return
                if time.monotonic() - pending["changed_at"] < 0.35:
                    continue
                amount = pending["amount"]
                headers = pending["headers"]
                changed_at = pending["changed_at"]

            try:
                patch_page_amount(page_id, amount, headers)
            except requests.RequestException as exc:
                with self.lock:
                    pending = self.pending.get(page_id)
                    if pending is not None and pending["changed_at"] == changed_at:
                        self.errors[page_id] = str(exc)
                        self.pending.pop(page_id, None)
                        self.workers.discard(page_id)
                        return
                continue

            with self.lock:
                pending = self.pending.get(page_id)
                if pending is not None and pending["changed_at"] == changed_at:
                    self.saved_at[page_id] = datetime.now()
                    self.pending.pop(page_id, None)
                    self.workers.discard(page_id)
                    return


@st.cache_resource
def get_syncer():
    return LatestAmountSyncer()


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
    amount = page_amount(page)
    return page["id"], int(amount)


def page_amount(page):
    return int(page["properties"].get("Amount", {}).get("number") or 0)


def fetch_page_amount(page_id):
    headers = notion_headers()
    resp = requests.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=headers, timeout=10)
    resp.raise_for_status()
    return page_amount(resp.json())


def list_users():
    """Return [(name, page_id, amount), ...] for all rows in the Counter database."""
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
                users.append((name, page["id"], page_amount(page)))
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


def patch_page_amount(page_id, amount, headers):
    payload = {"properties": {"Amount": {"number": max(0, int(amount))}}}
    resp = requests.patch(f"{NOTION_API_BASE}/pages/{page_id}", headers=headers, json=payload, timeout=10)
    resp.raise_for_status()


def get_or_create_user(username):
    page_id, amount = find_user_page(username)
    if page_id is None:
        page_id = create_user_page(username, 0)
        amount = 0
    return page_id, amount


def run_auto_sync():
    if st_autorefresh is not None:
        return st_autorefresh(interval=AUTO_SYNC_INTERVAL_MS, key="counter_auto_sync")
    return None

# Session defaults
st.session_state.setdefault("username", None)
st.session_state.setdefault("page_id", None)
st.session_state.setdefault("current_total", None)
st.session_state.setdefault("last_update", None)
st.session_state.setdefault("last_auto_sync_count", -1)
st.session_state.setdefault("save_error", None)

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
        for idx, (name, page_id, amount) in enumerate(existing_users):
            if cols[idx % 2].button(name, key=f"user_{page_id}", use_container_width=True):
                st.session_state.username = name
                st.session_state.page_id = page_id
                st.session_state.current_total = amount
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
        elif any(clean.lower() == u.lower() for u, _, _ in existing_users):
            st.warning("That name already exists — tap it above instead.")
        else:
            try:
                page_id, _ = get_or_create_user(clean)
                st.session_state.username = clean
                st.session_state.page_id = page_id
                st.session_state.current_total = 0
                st.rerun()
            except requests.HTTPError as exc:
                st.error(f"Could not reach Notion: {exc.response.status_code} {exc.response.text}")
            except requests.RequestException as exc:
                st.error(f"Could not reach Notion: {exc}")
    st.stop()

# --- Main screen ---
syncer = get_syncer()
auto_sync_count = run_auto_sync()
should_sync = st.session_state.current_total is None
if auto_sync_count is not None and auto_sync_count > 0 and auto_sync_count != st.session_state.last_auto_sync_count:
    st.session_state.last_auto_sync_count = auto_sync_count
    should_sync = not syncer.has_pending(st.session_state.page_id)

if should_sync:
    try:
        st.session_state.current_total = fetch_page_amount(st.session_state.page_id)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            # Row got deleted in Notion — recreate.
            st.session_state.page_id, st.session_state.current_total = get_or_create_user(
                st.session_state.username
            )
        else:
            st.error(f"Sync failed: {exc}")
            st.stop()
    except requests.RequestException as exc:
        st.error(f"Sync failed: {exc}")
        st.stop()

current_total = st.session_state.current_total


def handle_change(delta=0, absolute_total=None):
    previous_total = int(st.session_state.current_total or 0)
    next_total = previous_total + int(delta) if absolute_total is None else int(absolute_total)
    next_total = max(0, next_total)
    st.session_state.current_total = next_total
    st.session_state.last_update = datetime.now()

    headers = notion_headers()
    if headers is None:
        st.session_state.save_error = "Could not save your update: Notion API token is not configured."
    else:
        get_syncer().queue(st.session_state.page_id, next_total, headers)
        st.session_state.save_error = None


def handle_custom_change():
    amount = int(st.session_state.custom_amount)
    delta = amount if st.session_state.custom_action == "Add" else -amount
    handle_change(delta=delta)


st.title("💸 Savings")
st.caption(f"Signed in as **{st.session_state.username}**")
st.metric("Current total", f"{current_total} RMB")
sync_error, last_saved_at = syncer.status(st.session_state.page_id)
if st.session_state.save_error or sync_error:
    st.error(st.session_state.save_error or f"Could not save your update: {sync_error}")


st.write("#### Quick actions")
add_cols = st.columns(3)
for amount, col in zip((10, 50, 100), add_cols):
    with col:
        st.button(
            f"+{amount}",
            type="primary",
            use_container_width=True,
            key=f"add_{amount}",
            on_click=handle_change,
            kwargs={"delta": amount},
        )

sub_cols = st.columns(3)
for amount, col in zip((10, 50, 100), sub_cols):
    with col:
        st.button(
            f"-{amount}",
            use_container_width=True,
            key=f"sub_{amount}",
            on_click=handle_change,
            kwargs={"delta": -amount},
        )

with st.form("custom_form"):
    st.write("#### Custom")
    st.radio(
        "Action",
        ["Add", "Deduct"],
        horizontal=True,
        label_visibility="collapsed",
        key="custom_action",
    )
    st.number_input("Amount", min_value=1, max_value=100000, value=100, step=10, key="custom_amount")
    st.form_submit_button(
        "Save",
        type="primary",
        use_container_width=True,
        on_click=handle_custom_change,
    )

st.button("Reset to zero", use_container_width=True, on_click=handle_change, kwargs={"absolute_total": 0})

if st.button("Sign out", use_container_width=True):
    st.session_state.username = None
    st.session_state.page_id = None
    st.session_state.current_total = None
    st.session_state.last_auto_sync_count = -1
    st.session_state.save_error = None
    st.rerun()

st.caption("Synced with Notion — auto-refreshes every 15 seconds.")
if syncer.has_pending(st.session_state.page_id):
    st.caption("Saving to Notion...")
elif last_saved_at:
    st.caption(f"Saved to Notion: {last_saved_at.strftime('%H:%M:%S')}")
elif st.session_state.last_update:
    st.caption(f"Last update: {st.session_state.last_update.strftime('%H:%M:%S')}")

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
