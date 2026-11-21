# CivicPredict backend

## Render deployment

From the repository root, configure the backend as a free Render Web Service:

- Build command: `python -m pip install -r backend/requirements.txt`
- Start command: `cd backend && python -m uvicorn main:app --host 0.0.0.0 --port $PORT`

Set `CIVICPREDICT_FRONTEND_URL` to the frontend's exact HTTPS origin, for
example `https://civicpredict-frontend.onrender.com`. Local Vite origins remain
allowed for development; other origins are not.

The model files and datasets are loaded from `../ai-model/` relative to the
backend source file, so keep the `ai-model/` directory in the deployed
repository. Startup creates or migrates `backend/civicpredict.db`.

Render's free service filesystem is ephemeral. SQLite continues to work, but
data written at runtime (including predictions, incidents, and accounts) can be
lost when the service restarts or redeploys. The checked-in database is not a
durable hosted database; use a paid persistent disk or an external database if
records must survive.

The application currently defaults to `CIVICPREDICT_DEMO_MODE=true`, which
bypasses authentication and grants demo-operator access. CORS restrictions do
not secure the API. Do not expose this deployment to real users or store
sensitive data until authentication is enabled and the frontend supports it.

## Local demo

The local hackathon demo opens without login. Start the API from this directory
so the existing model and dataset paths resolve:

```powershell
python -m uvicorn main:app --reload
```

Authentication is bypassed for the local demo by default. The backend creates a
local, random-password demo-operator record as needed; it does not print, expose,
or use a hard-coded password. Set `CIVICPREDICT_DEMO_MODE=false` to restore
backend role enforcement for a future authenticated deployment. In that mode,
configure a stable `CIVICPREDICT_SECRET_KEY` of at least 32 bytes and bootstrap
the first administrator with `python main.py create-admin`.

The SQLite database is `backend/civicpredict.db`. Application startup applies
transactional, versioned schema migrations and preserves existing prediction
history. New areas are pending until an administrator records at least three
complete, attributable observations and explicitly verifies model readiness.

## Operational boundaries

- Complaint, incident, task, alert, notification-queue and prediction-feedback
  records are stored locally in SQLite. Role authorization remains available
  when demo mode is turned off.
- Notifications are internal queue records only. No SMS, email, WhatsApp, or
  other delivery provider is connected.
- Weather provider status is explicitly `not_configured`. Prediction continues
  using inputs supplied in the assessment form; old observations are not
  silently substituted for current weather.
- Predictions and anomaly data are based on the project's synthetic demo
  dataset/models. AI risk labels are early warnings, not confirmed failures or
  guarantees of service reliability.
- Demo mode intentionally has no user authentication or authorization boundary.
  Keep it local and do not enter sensitive personal data.
- The local demo is not production hardened. See the Render deployment warning
  above before exposing it to the public internet.
