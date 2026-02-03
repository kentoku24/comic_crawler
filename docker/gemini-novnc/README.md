# Gemini noVNC (arm64)

This runs a GUI **Chromium** inside Docker with noVNC (arm64-friendly).

## Run
```bash
docker compose up -d --build
```

Open: http://localhost:6080/vnc.html

Chrome profile is persisted in the `chrome-profile` volume.

## Security notes
- x11vnc is started with `-nopw` (no password). Bind ports to localhost or add a password.
- For safer exposure: use `- "127.0.0.1:6080:6080"` and SSH tunnel.

## Next steps (use OpenClaw Browser Relay)
Goal: you log in to Gemini inside the VNC session, then **attach that Gemini tab** so the agent can drive it.

1) Log into Gemini inside the VNC session.

2) Mount the OpenClaw Browser Relay unpacked extension into the container.

On the host machine (where `openclaw` CLI is installed):
```bash
# prints the extension directory (unpacked)
openclaw browser extension path
```

Then run the container with that directory mounted to `/opt/openclaw-relay`.
Example (compose override):
```yaml
# docker-compose.override.yml
services:
  gemini-novnc:
    volumes:
      - chrome-profile:/data/chrome
      - /ABS/PATH/TO/OPENCLAW-RELAY-EXT:/opt/openclaw-relay:ro
```

3) Restart the container, open the VNC session again, and confirm the extension is loaded.

4) Click the OpenClaw Browser Relay icon on the **Gemini tab** to Attach/Connect (badge ON).
