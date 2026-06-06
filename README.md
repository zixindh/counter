## RMB Counter Quick Guide

- **Goal**: Track each user's total RMB across devices, with quick add/deduct buttons.
- **Storage**: A Notion database (one row per user, columns `Name` + `Amount`). Phone and desktop see the same number because both read/write Notion.
- **Login**: Just type a username and click **Continue**. A new row is created in Notion the first time.
- **Setup**:
  1. Share the Notion database with your integration.
  2. Add the integration's secret token to Streamlit Cloud → *App settings → Secrets* as `Notion_API`.
  3. Locally you can instead `export Notion_API=<token>`.
- **Run**:
  - `pip install -r requirements.txt`
  - `streamlit run app.py`
- **Sync**: Button taps update the on-screen total immediately. The app writes the latest total to Notion in the background and still refreshes from Notion every 15 seconds for cross-device changes.
