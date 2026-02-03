# Gemini noVNC (arm64)

This runs a GUI Chrome inside Docker with noVNC.

## Run
```bash
docker compose up -d --build
```

Open: http://localhost:6080/vnc.html

Chrome profile is persisted in the `chrome-profile` volume.

## Security notes
- x11vnc is started with `-nopw` (no password). Bind ports to localhost or add a password.
- For safer exposure: use `- "127.0.0.1:6080:6080"` and SSH tunnel.

## Next steps
1) Log into Gemini inside the VNC session.
2) Install OpenClaw Browser Relay extension in that Chrome.
3) Attach the Gemini tab using the extension.
