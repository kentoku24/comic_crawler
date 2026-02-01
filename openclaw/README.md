# OpenClaw integration (no secrets)

This directory documents how to run this crawler under OpenClaw.

## What OpenClaw provides
- Scheduling (cron)
- Running the checker script on a cadence
- Posting messages to Discord channels

## You must NOT commit
- Discord bot tokens
- GitHub tokens
- Any cookies / login creds for manga sites

## Files
- `example-config.json5`: **template** OpenClaw config fragments (no secrets)
- `cron-job.md`: recommended cron payload behavior and schedule
