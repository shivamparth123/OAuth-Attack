from flask import Flask, request, render_template_string
import requests

app = Flask(__name__)

OAUTH_SERVER_INTERNAL = "http://oauth-server:8083"   # Docker network
CLIENT_ID    = "myapp_client"
REDIRECT_URI = "http://localhost:8081/callback"

# ─────────────────────────────────────────────────────────────
#  Templates  (design intentionally matches fake clone)
# ─────────────────────────────────────────────────────────────
LANDING = """
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
      transition: background .2s;
    }
    .btn:hover { background: #c73652; }
    .origin { margin-top: 24px; font-size: 12px; color: #555; }
  </style>
</head>
<body>
<div class="card">
  <h1>MyApp</h1>
  <p class="tagline">Your trusted productivity platform</p>
  <!-- LEGITIMATE: redirect_uri points to our own /callback -->
  <a class="btn" href="{{ oauth_url }}">Login with OAuth</a>
  <p class="origin">localhost:8081 — the REAL MyApp</p>
</div>
</body>
</html>
"""

# /callback: receives OAuth redirect with token in URL fragment
# JS extracts fragment and calls /dashboard
CALLBACK = """
<!DOCTYPE html>
<html>
<head><title>Logging in…</title></head>
<body style="font-family:Arial;display:flex;align-items:center;justify-content:center;height:100vh;background:#1a1a2e;color:#fff;">
<p id="msg">Processing login…</p>
<script>
  const frag    = window.location.hash.substring(1);
  const params  = new URLSearchParams(frag);
  const token   = params.get('access_token');
  const errMsg  = params.get('error');
  if (token) {
    window.location.href = '/dashboard?token=' + encodeURIComponent(token);
  } else {
    document.getElementById('msg').textContent = 'Login failed: ' + (errMsg || 'unknown error');
  }
</script>
</body>
</html>
"""

DASHBOARD = """
<!DOCTYPE html>
<html>
<head>
  <title>MyApp — Dashboard</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', Arial, sans-serif;
      background: #1a1a2e; color: #fff;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh;
    }
    .card {
      background: #16213e; border-radius: 14px;
      padding: 40px 48px; text-align: center;
      box-shadow: 0 6px 24px rgba(0,0,0,.4);
    }
    h2 { color: #e94560; font-size: 28px; margin-bottom: 8px; }
    .email { color: #aaa; margin-bottom: 20px; }
    .badge {
      display: inline-block; background: #0f3460;
      border: 1px solid #e94560; border-radius: 20px;
      padding: 6px 18px; font-size: 13px; margin-bottom: 20px;
    }
    .token-label { font-size: 11px; color: #555; margin-top: 12px; }
    .token {
      font-family: monospace; font-size: 11px;
      color: #888; word-break: break-all; max-width: 380px;
    }
  </style>
</head>
<body>
<div class="card">
  <h2>Welcome, {{ name }}!</h2>
  <p class="email">{{ email }}</p>
  <div class="badge">✅ Authenticated via OAuth</div>
  <p class="token-label">Access Token</p>
  <p class="token">{{ token }}</p>
</div>
</body>
</html>
"""

ERROR_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Error</title></head>
<body style="font-family:Arial;text-align:center;padding:60px;background:#1a1a2e;color:#e94560;">
  <h2>⚠️ {{ message }}</h2>
  <p style="color:#aaa;margin-top:12px">{{ detail }}</p>
  <a href="/" style="color:#e94560;margin-top:24px;display:inline-block;">← Back</a>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────────────
@app.route('/')
def index():
    oauth_url = (
        f"http://localhost:8083/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=token"
        f"&scope=read_profile"
    )
    return render_template_string(LANDING, oauth_url=oauth_url)


@app.route('/callback')
def callback():
    """OAuth redirects here. JS extracts the token from the URL fragment."""
    return render_template_string(CALLBACK)


@app.route('/dashboard')
def dashboard():
    token = request.args.get('token', '').strip()
    if not token:
        return render_template_string(
            ERROR_PAGE,
            message="No token provided",
            detail="You must log in first."
        ), 400
    try:
        resp = requests.get(
            f"{OAUTH_SERVER_INTERNAL}/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=3,
        )
        if resp.status_code != 200:
            return render_template_string(
                ERROR_PAGE,
                message="Invalid or expired token",
                detail=resp.text,
            ), 401
        user = resp.json()
    except Exception as e:
        return render_template_string(
            ERROR_PAGE,
            message="Could not reach OAuth server",
            detail=str(e),
        ), 502

    return render_template_string(
        DASHBOARD,
        name=user.get('name', 'Unknown'),
        email=user.get('email', 'Unknown'),
        token=token,
    )


@app.route('/health')
def health():
    return {"status": "ok", "server": "client-app (real MyApp)"}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, debug=True)
