"""
app_hardened.py  —  OAuth Server with FIXED redirect_uri validation
===================================================================
The only change from app.py is in authorize_get():
  - redirect_uri must EXACTLY match the registered URI for that client.
  - No prefix tricks, no open redirect.

Run this instead of app.py to show the "fixed" side of the demo.
"""

from flask import Flask, request, redirect, render_template_string, jsonify
import uuid, time

app = Flask(__name__)

TOKENS = {}

USERS = {
    "john": {
        "password": "password123",
        "name": "John Doe",
        "email": "john@example.com",
    }
}

CLIENTS = {
    "myapp_client": {
        "name": "MyApp",
        "registered_uri": "http://localhost:8081/callback",   # exact allowed URI
    }
}

AUTHORIZE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <title>OAuth Authorization (Hardened)</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', Arial, sans-serif;
      background: #f0f2f5;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh;
    }
    .card {
      background: #fff; border-radius: 12px;
      box-shadow: 0 4px 20px rgba(0,0,0,.12);
      width: 400px; padding: 36px;
    }
    .logo { font-size: 28px; font-weight: 700; color: #1a73e8; margin-bottom: 4px; }
    .subtitle { color: #666; font-size: 14px; margin-bottom: 20px; }
    .scope-box {
      background: #f8f9fa; border-radius: 8px;
      padding: 14px; margin: 18px 0; font-size: 14px; color: #333;
    }
    input {
      width: 100%; padding: 10px 12px; margin: 6px 0;
      border: 1px solid #ddd; border-radius: 8px; font-size: 14px;
    }
    input:focus { outline: none; border-color: #1a73e8; }
    .btn {
      width: 100%; padding: 12px; border: none; border-radius: 8px;
      cursor: pointer; font-size: 15px; font-weight: 600; margin-top: 10px;
    }
    .btn-allow { background: #1a73e8; color: #fff; }
    .btn-deny  { background: #f1f3f4; color: #444; }
    .fixed-badge {
      margin-top: 18px; padding: 10px; background: #d4edda;
      border: 1px solid #28a745; border-radius: 6px;
      font-size: 12px; color: #155724;
    }
  </style>
</head>
<body>
<div class="card">
  <div class="logo">🔐 OAuth Server (Hardened)</div>
  <div class="subtitle">
    <b>{{ client_name }}</b> is requesting access to your account.
  </div>
  <div class="scope-box">📋 <b>Requested Scope:</b> {{ scope }}</div>
  <form method="POST" action="/authorize">
    <input type="hidden" name="client_id"      value="{{ client_id }}">
    <input type="hidden" name="redirect_uri"   value="{{ redirect_uri }}">
    <input type="hidden" name="response_type"  value="{{ response_type }}">
    <input type="hidden" name="scope"          value="{{ scope }}">
    <input type="text"     name="username" placeholder="Username" value="john">
    <input type="password" name="password" placeholder="Password" value="password123">
    <button class="btn btn-allow" name="action" value="allow">✅ Allow Access</button>
    <button class="btn btn-deny"  name="action" value="deny">❌ Deny</button>
  </form>
  <div class="fixed-badge">
    ✅ <b>[HARDENED]</b> redirect_uri validated by exact match only.
  </div>
</div>
</body>
</html>
"""


@app.route('/authorize', methods=['GET'])
def authorize_get():
    client_id     = request.args.get('client_id', '')
    redirect_uri  = request.args.get('redirect_uri', '')
    response_type = request.args.get('response_type', 'token')
    scope         = request.args.get('scope', 'read_profile')

    if client_id not in CLIENTS:
        return "<h3>Error: Unknown client_id</h3>", 400

    # ╔══════════════════════════════════════════════════════════╗
    # ║  FIX: Exact match — any deviation is rejected outright  ║
    # ╚══════════════════════════════════════════════════════════╝
    registered = CLIENTS[client_id]['registered_uri']
    if redirect_uri != registered:
        print(f"[HARDENED] BLOCKED invalid redirect_uri: {redirect_uri}")
        return (
            f"<h3>403 — Invalid redirect_uri</h3>"
            f"<p>Provided:   <code>{redirect_uri}</code></p>"
            f"<p>Registered: <code>{registered}</code></p>"
            f"<p>Exact match required. Attack blocked.</p>"
        ), 403

    return render_template_string(
        AUTHORIZE_TEMPLATE,
        client_name=CLIENTS[client_id]['name'],
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type=response_type,
        scope=scope,
    )


@app.route('/authorize', methods=['POST'])
def authorize_post():
    action       = request.form.get('action')
    redirect_uri = request.form.get('redirect_uri', '')
    username     = request.form.get('username', '')
    password     = request.form.get('password', '')

    # Re-validate on POST as well (defense-in-depth)
    client_id  = request.form.get('client_id', '')
    registered = CLIENTS.get(client_id, {}).get('registered_uri', '')
    if redirect_uri != registered:
        return "<h3>403 — Invalid redirect_uri on POST</h3>", 403

    if action == 'deny':
        return redirect(f"{redirect_uri}?error=access_denied")

    user = USERS.get(username)
    if not user or user['password'] != password:
        return "<h3>Error: Invalid credentials</h3>", 401

    token = str(uuid.uuid4())
    TOKENS[token] = {
        "sub":       username,
        "name":      user['name'],
        "email":     user['email'],
        "issued_at": time.time(),
    }

    return redirect(f"{redirect_uri}#access_token={token}&token_type=bearer")


@app.route('/userinfo')
def userinfo():
    auth  = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '').strip()
    user  = TOKENS.get(token)
    if not user:
        return jsonify({"error": "invalid_token"}), 401
    return jsonify(user)


@app.route('/health')
def health():
    return jsonify({"status": "ok", "server": "oauth-server-HARDENED"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8083, debug=True)
