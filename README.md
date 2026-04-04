# OAuth redirect_uri Misconfiguration — Attack Demo

A fully self-contained localhost demo of **CWE-601 / OAuth open redirect** caused by missing `redirect_uri` validation on the authorization server.

---

## Architecture

| Service | URL | Role |
|---------|-----|------|
| `oauth-server` | http://localhost:8083 | Vulnerable OAuth server (no redirect_uri check) |
| `client-app` | http://localhost:8081 | Legitimate MyApp (innocent, correct) |
| `attacker-server` | http://localhost:8082 | Fake clone + token collector + console |
| `mailhog` | http://localhost:8025 | Fake victim inbox (MailHog) |

---

## Quick Start

```bash
git clone <repo>
cd oauth-attack-demo
docker compose up --build
```

Wait ~15 seconds for all services to be ready.

---

## Full Demo Walkthrough

### Step 1 — Show the REAL MyApp (Victim's perspective, normal flow)

Open **http://localhost:8081**

- Click **Login with OAuth**
- You land on the real OAuth consent screen (localhost:8083)
- Enter credentials: `john` / `password123`, click Allow
- You land on the real MyApp dashboard ✅

Note the correct OAuth URL in the browser:
```
http://localhost:8083/authorize
  ?client_id=myapp_client
  &redirect_uri=http://localhost:8081/callback   ← correct
  &response_type=token
  &scope=read_profile
```

---

### Step 2 — Attacker sends the phishing email

Open **http://localhost:8082/console** (attacker's view)

Click **"📧 Send Phishing Email via MailHog"**

---

### Step 3 — Victim checks their inbox

Open **http://localhost:8025** (MailHog — victim's inbox)

- See the realistic phishing email from `noreply@myapp.com`
- Subject: *"Your MyApp session has expired — please re-login"*
- Click the **"Login to MyApp"** button

---

### Step 4 — Victim on the fake clone

Victim lands on **http://localhost:8082** — a pixel-perfect clone of MyApp.

Clicks **"Login with OAuth"**

Note the malicious OAuth URL:
```
http://localhost:8083/authorize
  ?client_id=myapp_client
  &redirect_uri=http://localhost:8082/collect    ← ATTACKER'S server
  &response_type=token
  &scope=read_profile
```

---

### Step 5 — Victim approves on the real OAuth screen

The OAuth consent screen is **completely real** (localhost:8083).  
The victim logs in normally. Clicks **Allow**.

Because `redirect_uri` is **never validated**, the OAuth server sends the token to `localhost:8082/collect`.

---

### Step 6 — Token silently stolen, victim redirected to real MyApp

- `/collect` JS extracts the token from the URL fragment
- POSTs it to `/steal` (server-side)
- Attacker fetches victim's name + email using the stolen token
- Victim is **immediately redirected** to the real MyApp dashboard

**Victim sees their real MyApp dashboard — zero suspicion.**

---

### Step 7 — Check the attacker console

Open **http://localhost:8082/console**

```
[STOLEN]   Token : <uuid>
[USERINFO] Name  : John Doe
[USERINFO] Email : john@example.com
[TIME]           : 2024-03-31 14:32:01
```

---

## The Vulnerability (One Paragraph)

The OAuth server's `/authorize` endpoint accepts **any** `redirect_uri` without validation.  
A legitimate OAuth server must perform an **exact string match** against the URI(s) registered for that `client_id`.  
Using prefix matching, substring matching, or no matching at all allows an attacker to substitute their own server as the redirect target, receiving the access token directly.

### Vulnerable code (`app.py`)
```python
# No validation at all — any redirect_uri is accepted
@app.route('/authorize', methods=['GET'])
def authorize_get():
    redirect_uri = request.args.get('redirect_uri', '')
    # ← missing: check redirect_uri against registered value
    ...
```

### Fixed code (`app_hardened.py`)
```python
registered = CLIENTS[client_id]['registered_uri']
if redirect_uri != registered:           # exact match only
    return "Invalid redirect_uri", 403
```

---

## To Demo the Fix

In `docker-compose.yml`, change the oauth-server CMD to use `app_hardened.py`:

```yaml
  oauth-server:
    ...
    command: ["python", "app_hardened.py"]
```

Restart:
```bash
docker compose up --build
```

Now re-run the attack: the OAuth server will **block the malicious redirect_uri with a 403** and the attack fails.

---

## Real-World Analogue

On a real domain, the subdomain trick makes this even more dangerous:

| | URI |
|--|--|
| Registered | `https://myapp.com` |
| Attacker's domain | `https://myapp.com.attacker.com` |
| Prefix match check | `"https://myapp.com.attacker.com".startswith("https://myapp.com")` → **True** ✅ |

The token is delivered to `attacker.com` while the prefix check passes. Exact matching closes this entirely.

---

## References

- [RFC 6749 §10.6 — Authorization Code Redirection URI Manipulation](https://datatracker.ietf.org/doc/html/rfc6749#section-10.6)
- [OAuth 2.0 Security Best Current Practice §4.1](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-security-topics)
- [CWE-601: URL Redirection to Untrusted Site](https://cwe.mitre.org/data/definitions/601.html)
- [PortSwigger — OAuth redirect_uri flaws](https://portswigger.net/web-security/oauth)
