# Prompt: set up Moomoo OpenD on the VPS

Paste everything below the line into Claude Code (or another assistant) running on
the VPS. You type every password and verification code yourself; the assistant never
sees them.

---

You are helping me set up Moomoo OpenD (market-data gateway) on this Ubuntu VPS
(Hostinger KVM) for my options research repo. Work step by step, show me each
command before running anything that changes the system, and stop to let me act
whenever a step needs my credentials.

**Hard security rules (do not break these):**
1. Never ask me for, read, print, store or type my moomoo login password, my
   trade/unlock password, or any verification code. When a step needs one, tell me
   exactly where to enter it and wait until I confirm it is done.
2. OpenD must listen on 127.0.0.1 only. Never open port 11111 (API) or the OpenD
   telnet/console port to the internet, in ufw or in the Hostinger hPanel firewall.
3. Market data only. Do not unlock trading, place orders, or call any trade API.
4. Any config file holding my login must be `chmod 600`, owned by the service user,
   and never committed to git (add it to `.gitignore` if it lives near the repo).

**Steps:**
1. Check the box: `lsb_release -a`, CPU/RAM/disk, Python version, timezone. Install
   `python3-venv python3-pip git tmux ufw` if missing.
2. Firewall: enable ufw with SSH allowed and everything else denied inbound. Show me
   `ufw status`. Remind me to mirror this in the hPanel firewall.
3. Repo: clone `https://github.com/longansoju/options` into `~/options`, check out
   branch `claude/planning-session-ipr02p`, create `.venv`, then
   `pip install -r requirements.txt moomoo-api`. Read `docs/moomoo_setup.md` and
   `deploy/vps_setup.md` before going further, and follow them where they agree
   with these rules.
4. OpenD: find the current Linux command-line OpenD download on moomoo's official
   OpenAPI docs site (openapi.moomoo.com), download and extract it into `~/opend`.
   Open its config file and set the listen IP to 127.0.0.1 and the API port to
   11111. Show me which lines hold the login account and password and **let me fill
   them in myself** (prefer the MD5-password field if the version supports it).
5. First start in `tmux`. The first login from a new server will probably ask for a
   phone/SMS verification code: show me the console command from moomoo's docs for
   entering it, and wait while I enter it.
6. Verify: confirm the port is bound to 127.0.0.1 only (`ss -ltnp`), then run
   ```
   cd ~/options && source .venv/bin/activate
   export MARKET_DATA_PROVIDER=moomoo MOOMOO_OPEND_HOST=127.0.0.1 MOOMOO_OPEND_PORT=11111 MOOMOO_MARKET=US
   python -c "from data_ingestion.moomoo_provider import MoomooProvider as M; c=M().options_chain('AAPL'); print(c.spot_price, len(c.contracts)); print(c.contracts[:3])"
   ```
   If it errors or the fields look wrong, show me the raw response from the moomoo
   SDK (`get_option_chain` / `get_market_snapshot`) for one AAPL contract, so the
   field mapping in `data_ingestion/moomoo_provider.py` can be fixed. If the chain
   comes back empty or delayed, say so: my account may need a US-options API quote
   entitlement, which I will check in the moomoo app.
7. Ask me to compare 2-3 strikes (bid/ask/last, IV if shown) against the moomoo app.
8. Only after step 7 checks out: create a systemd service for OpenD that restarts on
   failure and starts on boot, running as a non-root user, and show me the unit file
   before enabling it.
9. Summarise what was installed, where the config lives, how to restart OpenD, and
   which steps still need me (verification code on future re-logins). Do not set up
   cron jobs or disable the GitHub Action yet — I will do that with the main
   analysis session once real data is confirmed.
