# KOLAPSE Backend

KOLAPSE is an elderly-care monitoring platform that combines camera-based AI activity detection, fall alerts, caregiver monitoring, and real-time notifications.

This repository contains the KOLAPSE FastAPI backend and PostgreSQL integration.

The AI inference service is deployed separately and is not bundled inside the backend Docker image.

---

## 1. Current System Architecture

KOLAPSE is separated into the following components:

```text
Public KOLAPSE Website
        |
        v
Customer Service Request
        |
        v
KOLAPSE Admin Dashboard
        |
        +--> Create Customer
        +--> Register Elder
        +--> Register Camera
        +--> Generate Camera Device Key
        |
        v
Customer Google Login
        |
        v
Customer Dashboard
        |
        v
FastAPI Backend
        |
        +--> PostgreSQL
        +--> Telegram Notifications
        +--> WebSocket Events
        |
        ^
        |
Runpod AI Service
        |
        +--> YOLOv8n
        +--> MediaPipe
        +--> CNN-LSTM
        |
        ^
        |
Customer Camera
```

---

## 2. Backend Technology

- Python 3.10
- FastAPI
- Uvicorn
- PostgreSQL
- SQLAlchemy
- Psycopg
- Pydantic
- JWT authentication
- Google OAuth authentication
- Telegram Bot integration
- WebSocket events
- Docker
- Docker Compose

---

## 3. Authentication and Authorization

KOLAPSE uses multiple security layers.

### Google OAuth

Google verifies the identity of the user.

A Google account cannot automatically access KOLAPSE simply because Google authentication succeeds.

The email must already exist as an approved KOLAPSE user.

### KOLAPSE JWT

After successful authentication, the backend creates a KOLAPSE JWT access token.

The frontend uses this token when communicating with protected backend endpoints.

### Database Roles

User authorization is controlled by the `role` stored in PostgreSQL.

Current roles include:

- `admin`
- `customer`

Google does not determine the user's role.

### Admin

Admins can manage customers, elders, plans, account status, and cameras.

### Customer

Customers can access only the information associated with their own account.

Customers cannot promote themselves to administrators.

---

## 4. Main Database Entities

The PostgreSQL database currently contains:

- `users`
- `elders`
- `cameras`
- `activity_logs`
- `alerts`
- `notification_channels`

Relationships between these records are used to isolate customer data.

For example:

```text
Customer
   |
   v
Elder
   |
   v
Camera

Elder
   |
   +--> Activity Logs
   |
   +--> Alerts
```

---

## 5. Camera Registration

Cameras are registered through the Admin Dashboard.

The general flow is:

```text
Admin
  |
  v
Customer
  |
  v
Elder
  |
  v
Register Camera
  |
  v
Generate Device Key
```

Camera device keys must be treated as credentials.

Do not commit camera device keys to Git.

Rotate exposed or compromised device keys before production use.

An `Active` camera record currently means that the camera is enabled in the KOLAPSE database. It does not necessarily mean that the physical camera is currently online.

---

## 6. AI Integration

The AI service runs separately from this backend.

Current AI pipeline:

```text
Camera / Video
      |
      v
YOLOv8n Person Detection
      |
      v
MediaPipe Pose
      |
      v
16 Angular Features
      |
      v
30-Frame Sequence
      |
      v
CNN-LSTM
      |
      v
Activity Prediction
```

Current activity classes include:

- Falling
- Lying
- Sitting
- Standing

The cloud AI environment has been tested separately on Runpod.

The AI service sends activity predictions to the KOLAPSE backend.

The AI service must authenticate to the backend using the configured AI service credentials and appropriate camera identity.

The production camera-to-cloud transport must use a secure connection. Do not expose customer RTSP camera ports directly to the public internet.

---

## 7. Fall Alerts

When a fall prediction reaches the configured confidence threshold, the backend can:

1. Store the activity.
2. Create a fall alert.
3. Apply duplicate-alert cooldown.
4. update the customer dashboard.
5. Push realtime events.
6. Send a Telegram notification when configured.

Relevant environment settings include:

```env
FALL_CONFIDENCE_THRESHOLD=0.80
FALL_ALERT_COOLDOWN_SECONDS=20
```

---

## 8. Telegram Integration

KOLAPSE supports Telegram notification onboarding.

Customers can connect their Telegram account through the KOLAPSE Telegram bot.

Notification-channel information is stored in PostgreSQL.

The Telegram bot token is a production secret and must never be committed to Git.

---

## 9. Environment Configuration

The real `.env` file is private and must not be committed.

Use:

```text
.env.example
```

as the configuration template.

A production environment must configure values for:

```env
APP_NAME=KOLAPSE API
APP_ENV=production
DEBUG=false
API_PREFIX=/api/v1

DATABASE_URL=...

JWT_SECRET=...
JWT_ALGORITHM=HS256
ACCESS_TOKEN_MINUTES=1440

GOOGLE_CLIENT_ID=...

FRONTEND_URL=...
EXTRA_CORS_ORIGINS=...

AI_API_KEY=...

FALL_CONFIDENCE_THRESHOLD=0.80
FALL_ALERT_COOLDOWN_SECONDS=20

TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

The current single-camera AI prototype may additionally use:

```env
CAMERA_DEVICE_KEY=...
```

Do not reuse development secrets for production.

Generate new production credentials before deployment.

---

## 10. Local Docker Deployment

The backend has been tested locally with Docker.

The current local architecture is:

```text
Frontend Docker / Nginx
        |
        v
FastAPI Docker
        |
        v
PostgreSQL Docker
```

Start the backend and PostgreSQL with:

```bash
docker compose up -d
```

Check running containers with:

```bash
docker compose ps
```

Backend API:

```text
http://localhost:8000
```

Swagger:

```text
http://localhost:8000/docs
```

---

## 11. Backend Dockerfile

The backend Docker image:

1. Uses Python 3.10.
2. Installs `requirements.txt`.
3. Copies the FastAPI application.
4. Starts Uvicorn.
5. Exposes the backend through port 8000.

The AI model/runtime is intentionally not installed in this backend container.

---

## 12. PostgreSQL

PostgreSQL is required by KOLAPSE.

Production PostgreSQL must use:

- Strong database credentials
- Persistent storage
- Regular backups
- Restricted network access
- Production environment variables

Do not use development database passwords in production.

The production deployment must ensure that PostgreSQL data survives container and server restarts.

---

## 13. Existing Database Migration

KOLAPSE already has existing development/test data.

Before migrating any database:

1. Create a PostgreSQL backup.
2. Verify the backup.
3. Prepare the production PostgreSQL database.
4. Restore the data.
5. Verify table counts and relationships.
6. Test admin access.
7. Test customer access.
8. Test elder/camera ownership.

Do not delete the original database until the production migration has been verified.

---

## 14. Google OAuth Production Setup

The frontend uses Google OAuth.

When the final production frontend domain is available, add it to the Google OAuth application's:

```text
Authorized JavaScript origins
```

For example:

```text
https://your-production-domain.com
```

The production backend must also allow the production frontend through CORS.

Google OAuth authenticates identity.

KOLAPSE PostgreSQL determines whether the authenticated account is an approved admin or customer.

---

## 15. Frontend Deployment

The frontend is a separate React + Vite application.

The frontend Docker build requires:

```env
VITE_API_URL=...
VITE_GOOGLE_CLIENT_ID=...
```

These Vite variables are injected during the frontend build.

For production:

```text
VITE_API_URL=https://your-production-api-domain
```

Do not leave the production frontend pointing to:

```text
http://127.0.0.1:8000
```

The production frontend domain must also be configured in Google OAuth.

---

## 16. CORS

The backend must allow the real production frontend origin.

Development origins may include:

```text
http://localhost:5173
http://localhost:8080
```

Production should include the final HTTPS frontend domain.

Old/decommissioned frontend domains should be removed when no longer required.

---

## 17. HTTPS and Domain

Production must use HTTPS.

Expected production structure:

```text
https://your-kolapse-domain.com
        |
        v
Frontend

https://api.your-kolapse-domain.com
        |
        v
FastAPI
```

Cloudflare or the selected reverse-proxy/server configuration can provide DNS and HTTPS.

The FastAPI container itself can remain on an internal HTTP port behind the HTTPS reverse proxy.

---

## 18. Production Deployment Responsibilities

### KOLAPSE Project Owner

Responsible for:

- Application source code
- Database schema and application data
- AI system
- Environment requirements
- Google OAuth configuration ownership
- Telegram bot ownership
- Production credential ownership
- Database backups
- Final application validation

### Deployment Engineer

Responsible for:

- Production server configuration
- Docker deployment
- PostgreSQL deployment
- Persistent database storage
- Production environment configuration
- Reverse proxy
- Domain connection
- HTTPS
- Container restart configuration
- Infrastructure validation

Do not share personal Google, Gmail, Telegram, or other account passwords.

Where possible, provide collaborator access or only the specific deployment credentials required.

---

## 19. Production Secrets

Before production deployment, rotate or generate new:

- PostgreSQL password
- JWT secret
- AI API key
- Exposed camera device keys
- Telegram bot token if previously exposed

Never commit these values.

They belong only in the production environment.

---

## 20. Runpod AI After Backend Deployment

Do not reconnect the cloud AI until the backend has a stable public HTTPS endpoint.

After backend deployment:

1. Confirm the public backend API works.
2. Prepare persistent Runpod storage.
3. Restore the AI environment/model.
4. Set the Runpod `BACKEND_BASE_URL`.
5. Configure the production AI API key.
6. Configure the correct camera identity.
7. Re-enable AI activity sending.
8. Test AI-to-backend communication.
9. Test dashboard activity updates.
10. Test fall alerts.
11. Test Telegram notifications.

Example:

```text
BACKEND_BASE_URL=https://api.your-kolapse-domain.com
```

Do not point Runpod at `localhost`.

---

## 21. Final Production Test

The final end-to-end test should verify:

```text
Camera
   |
   v
Cloud AI
   |
   v
FastAPI
   |
   +--> PostgreSQL
   |
   +--> Customer Dashboard
   |
   +--> Fall Alert
   |
   +--> Telegram
```

Verify both admin and customer isolation.

A customer must never be able to access another customer's elder, camera, activity, alert, or notification data.

---

## 22. Current Project Status

The following have been tested locally:

- FastAPI backend
- PostgreSQL
- Dockerized backend
- Dockerized frontend
- Google OAuth
- JWT authentication
- Admin/customer roles
- Admin Dashboard
- Customer Dashboard
- Customer creation
- Elder registration
- Camera registration
- Camera device-key generation
- Customer data isolation
- Existing database migration into Docker
- Telegram onboarding
- Fall alert flow
- AI inference locally
- AI inference on Runpod

Production deployment, secure production camera transport, Runpod reconnection, and final production end-to-end validation remain deployment-stage tasks.

---

## Security Notice

KOLAPSE processes monitoring information related to elderly care.

The current system should be treated as an innovation/MVP system unless and until appropriate production security, privacy, reliability, regulatory, and operational requirements have been independently validated.

KOLAPSE should not be represented as a replacement for emergency services or professional medical monitoring.