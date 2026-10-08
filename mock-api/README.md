# Local Mock API

This is a development and test fixture for exercising migrated EUCs locally.
It does not use real credentials, contact external services, or send
notifications.

## Install

From this directory, create or activate a Python environment and install the
fixture dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Start

Run the service on port 8001:

```powershell
python -m uvicorn app:app --host 0.0.0.0 --port 8001
```

## Endpoints

### Health

```http
GET http://localhost:8001/health
```

Returns:

```json
{"status": "ok"}
```

### Token

```http
POST http://localhost:8001/auth/token
Content-Type: application/json
```

```json
{
  "client_id": "any-local-value",
  "client_secret": "any-local-value"
}
```

Returns a deterministic `mock-access-token`. Credentials are not validated.

### Customer

```http
GET http://localhost:8001/customers?customer_id=12345
```

The `12345` customer returns the documented active customer fixture. Other
non-empty IDs return a deterministic active customer object as well.

### Notification

```http
POST http://localhost:8001/notifications
Content-Type: application/json
```

Any JSON object is accepted and acknowledged with:

```json
{
  "success": true,
  "received": true
}
```

No notification is sent externally.

## Docker networking

When the migrated EUC runs inside Docker on Windows, configure it with these
URLs. Do not use `localhost` from inside the container:

```text
http://host.docker.internal:8001/auth/token
http://host.docker.internal:8001/customers
http://host.docker.internal:8001/notifications
```

This service is only a local test fixture. It must not be used as a production
authentication, customer, or notification service.
