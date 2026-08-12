# FastAPI Boilerplate with SQLAlchemy Integration

This repository demonstrates a FastAPI application with JWT authentication, Argon2 password hashing, and SQLAlchemy async ORM for PostgreSQL.

The project includes:
- Login and signup flows
- JWT access and refresh token support
- Admin account management: disable, enable, restore, delete
- Self-service account restore and password change
- Short-lived restore tokens for account recovery
- Rate limiting and CORS support

## Prerequisites

- Python 3.11+
- Docker & Docker Compose (recommended)
- PostgreSQL for production

## Docker Setup (Recommended)

1. Clone the repository.
2. Create a `.env` file in the repo root.
3. Start services:

```bash
docker-compose up -d
```

### Required `.env` values for Docker

```env
SECRET_KEY=your_very_secret_key_at_least_32_chars
DATABASE_PASSWORD=your_db_password
ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
RATE_LIMIT_DEFAULT=100/minute
KILL_SWITCH_ENABLED=false
```

Docker Compose uses PostgreSQL and injects the connection settings into the API container.

## Local Development Setup

Create a `.env` file in the repository root with these values:

```env
SECRET_KEY=your_very_secret_key_at_least_32_chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=790
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USER=postgres
DATABASE_PASSWORD=your_db_password
DATABASE_NAME=myapp_db
DATABASE_SCHEMA=public
DATABASE_SSLMODE=prefer
ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
KILL_SWITCH_ENABLED=false
RATE_LIMIT_DEFAULT=100/minute
LOG_FILEPATH=./logs/
MEMORY_COST=65536
PARALLELISM=2
HASH_LENGTH=32
SALT_LENGTH=16
```

### Notes on environment variables

- `SECRET_KEY`: Secret used for JWT signing. Must be at least 32 characters in production.
- `ALGORITHM`: JWT algorithm (default `HS256`).
- `ACCESS_TOKEN_EXPIRE_MINUTES`: Access token lifetime in minutes.
- `DATABASE_*`: PostgreSQL connection settings.
- `ALLOWED_ORIGINS`: Comma-separated CORS origins.
- `KILL_SWITCH_ENABLED`: Enable manual maintenance mode.
- `RATE_LIMIT_DEFAULT`: Default rate limit, e.g. `100/minute`.
- `LOG_FILEPATH`: Directory for logs.
- `MEMORY_COST`, `PARALLELISM`, `HASH_LENGTH`, `SALT_LENGTH`: Argon2 hashing parameters.

## Database Setup

The application uses PostgreSQL with async SQLAlchemy. The user model includes:

- `id`
- `name`
- `email`
- `password_hash`
- `profile_pic`
- `user_role`
- `is_active`
- `disabled`
- `is_deleted`
- `deleted_at`
- `created_at`
- `updated_at`

### Apply migrations

```bash
alembic upgrade head
```

### Optional: Auto-create an admin user

A helper exists in `App/repository/UserRepository.py` named `create_admin_if_not_exists`. Use it to seed a default admin account after migrations.

```python
import asyncio
from App.api.dependencies.auth import get_password_hash
from App.repository.UserRepository import UserRepository
from App.core.Connector import database

async def create_admin():
    await database.connect()
    async with database.session() as session:
        await UserRepository.create_admin_if_not_exists(
            session=session,
            email="admin@example.com",
            password_hash=get_password_hash("Admin@123456"),
            name="System Administrator",
            role="admin",
            tier="enterprise"
        )

if __name__ == "__main__":
    asyncio.run(create_admin())
```

Run this script after `alembic upgrade head` to ensure the admin account is created.

> The project does not use `App/GetEnvDate.py`; database URL is configured through `App/core/settings.py`.

## Application Structure

The main FastAPI application is in `main.py` and mounts routes under the `/app/v1` prefix.

### Router prefixes

- Authentication: `/app/v1/auth/basic_auth`
- Admin routes: `/app/v1/admin/admin_access`
- User routes: `/app/v1/users/users_config`

## Key Endpoints

### Authentication

- `POST /app/v1/auth/basic_auth/login`
  - Request body: `username`, `password`
  - Returns access and refresh tokens or sets a `CSO` cookie when using cookie mode.

- `POST /app/v1/auth/basic_auth/signup`
  - Request body: `name`, `email`, `password`, `profile_pic`
  - Creates a new user.

### Refresh Token

- `POST /app/v1/users/users_config/refresh`
  - Request body: `refresh_token`
  - Returns a new access token.

### Current User

- `GET /app/v1/users/me`
  - Returns profile data for the authenticated user.

### Admin / Users

- `GET /app/v1/users/users?skip=0&limit=100&search=...`
  - Admin-only list users endpoint.

### Admin account management

- `POST /app/v1/admin/admin_access/account/disable/{user_id}`
  - Disable a user account.

- `POST /app/v1/admin/admin_access/account/enable/{user_id}`
  - Enable a disabled or inactive account.

- `POST /app/v1/admin/admin_access/account/restore/{user_id}`
  - Restore a deleted or disabled account.

- `POST /app/v1/admin/admin_access/account/temp_token/{user_id}`
  - Create a short-lived token for account restoration or password reset.

- `PUT /app/v1/admin/admin_access/account/password/{user_id}`
  - Update a user password.

- `DELETE /app/v1/admin/admin_access/account/{user_id}`
  - Soft delete a user account.

## Example Request Bodies

### Signup

```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "password": "StrongPass123!",
  "profile_pic": "https://example.com/avatar.png"
}
```

### Update Account

Use `PATCH /app/v1/admin/admin_access/account/{user_id}` with any of:

```json
{
  "name": "New Name",
  "email": "new@example.com",
  "password": "NewPass123!",
  "profile_pic": "https://example.com/new.png",
  "user_role": "user",
  "disable": false
}
```

### Delete Account

- Admin can delete any user except themselves.
- Normal users can delete their own account with `password` verification.

## Running Locally

```bash
uvicorn main:app --reload
```

## Logging

Logs are written to the directory configured by `LOG_FILEPATH` in `.env`.

## Security

- Argon2 is used for password hashing.
- JWT tokens secure authentication.
- Rate limiting and a kill-switch middleware are included.

## Notes

- Replace placeholder values in `.env` with your real configuration.
- Ensure PostgreSQL is running and migrations are applied before starting the app.
- The admin and user routes are mounted under `/app/v1`.

---

Private project: `iotNoob` by Talha.
