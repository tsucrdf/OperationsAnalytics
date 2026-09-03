# Conductor Report Board (Streamlit)

Upload a conductor ticketing report (CSV or Excel) and see buses, routes,
revenue and ridership per day, split by online vs. cash sales.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy from GitHub with auto-deploy (Streamlit Community Cloud)

This is the standard "push to git → app updates itself" setup for Streamlit,
and it's free for public repos.

1. **Create a GitHub repo** and push these three files to it (`app.py`,
   `requirements.txt`, this `README.md`) at the repo root, or under a
   subfolder if you prefer:
   ```bash
   git init
   git add app.py requirements.txt README.md
   git commit -m "Conductor report board"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin main
   ```

2. **Go to** [share.streamlit.io](https://share.streamlit.io) and sign in
   with your GitHub account.

3. Click **"New app"**, then:
   - Pick the repo and branch (`main`)
   - Set **Main file path** to `app.py` (or `streamlit_app/app.py` if you
     put it in a subfolder)
   - Click **Deploy**

4. That's it — **auto-deploy is on by default.** Every time you `git push`
   to the branch the app is connected to, Streamlit Community Cloud
   automatically detects the commit and redeploys within a minute or two.
   You'll see the deploy status in the app's dashboard on share.streamlit.io.

### Notes
- If you rename `app.py` or move it, update the "Main file path" in the
  app's settings (⋮ menu → Settings → General) or the redeploy will fail.
- Any new package you add to `requirements.txt` gets installed
  automatically on the next deploy — no separate step needed.
- Community Cloud apps for **public repos** are free; for a **private repo**
  you'll need a GitHub account linked with the right access permissions,
  which Streamlit's OAuth flow prompts for the first time you deploy from one.
- If you'd rather deploy on infrastructure Anthropic doesn't have visibility
  into (Render, Fly.io, a VM with a systemd service + git webhook, etc.),
  the same `app.py` + `requirements.txt` work unchanged — only the
  auto-deploy trigger setup differs from the GitHub Actions / webhook side.
