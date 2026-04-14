# Security Runbook

## 1) Suspected Credential Leak

1. Rotate exposed keys immediately:
   - `GROQ_API_KEY`
   - `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
   - OAuth client secrets
2. Redeploy services with new secrets.
3. Invalidate active sessions/tokens where feasible.
4. Review audit logs for suspicious actions.

## 2) OAuth Token Abuse or Compromise

1. Mark affected account as disconnected.
2. Revoke token from Google security console if required.
3. Delete encrypted token record for the affected tenant.
4. Require reconnect via OAuth flow.

## 3) Incident Response Checklist

- Capture timeline and impact
- Freeze risky operations if needed
- Patch root cause
- Rotate related secrets
- Notify impacted users when appropriate
- Document postmortem and prevention tasks

## 4) Key Rotation Policy

- Rotate API keys at defined intervals (e.g., 60-90 days)
- Rotate immediately after any public exposure
- Use least-privilege credentials for all integrations

