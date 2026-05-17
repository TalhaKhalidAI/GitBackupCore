 # FastAPI User Authentication & Management System

A production-ready FastAPI boilerplate with SQLite database, JWT authentication, and role-based access control.

## Made by Talha Khalid

## Features

### Authentication
- JWT-based authentication with Argon2 password hashing
- Login/Signup with email validation
- Password strength validation (uppercase, lowercase, digit, special character)
- Token-based session management

### User Management
- User registration and login
- Profile viewing and editing
- Password change and reset (admin can reset any user password)
- Account activation/deactivation
- Soft delete with restore capability

### Role-Based Access Control
- **Admin Role**: Full access to all user data and management
- **User Role**: Limited to own profile management

### Security
- Password hashing with Argon2
- JWT tokens with configurable expiration
- Role-based authorization
- Input validation with Pydantic
- SQL injection protection via SQLAlchemy

## Tech Stack

- **Framework**: FastAPI
- **Database**: SQLite (via SQLAlchemy)
- **Authentication**: JWT with Argon2 password hashing
- **Validation**: Pydantic v2
- **Rate Limiting**: SlowAPI
- **Logging**: Python logging

## Installation

### 1. Clone the repository
```bash
git clone https://github.com/iot-Noob/API-Boiler-Plate.git
cd API-Boiler-Plate
```

### 2. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
Edit the `.env` file with your settings:

```env
# Security (REQUIRED)
SECRET_KEY=your-secret-key-here-min-32-chars-long!
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=790

# Database
SQLITE_DATABASE_URL=sqlite:///./app.db

# Logging
LOG_FILEPATH=./logs/

# Rate Limiting
RATE_LIMIT_DEFAULT=100/minute

# Maintenance
KILL_SWITCH_ENABLED=false

# Argon2 Hashing
MEMORY_COST=65536
PARALLELISM=2
HASH_LENGTH=32
SALT_LENGTH=16

# Admin User (REQUIRED)
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=Admin@123

# Environment
ENVIRONMENT=development
ALLOWED_ORIGINS=*
```

### 5. Run the application
```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/app/v1/users/signup` | Register new user |
| POST | `/app/v1/users/login` | Login and get token |

### User Management
| Method | Endpoint | Description | Access |
|--------|----------|-------------|--------|
| GET | `/app/v1/users/me` | Get current user profile | User |
| GET | `/app/v1/users/` | List all users | Admin |
| GET | `/app/v1/users/{id}` | Get user by ID | User (own), Admin (any) |
| PUT | `/app/v1/users/{id}` | Update user | User (own), Admin (any) |
| DELETE | `/app/v1/users/{id}` | Delete user | User (own), Admin (any) |
| POST | `/app/v1/users/change-password` | Change own password | User |
| POST | `/app/v1/users/{id}/reset-password` | Reset user password | Admin |
| POST | `/app/v1/users/{id}/activate` | Activate user | Admin |
| POST | `/app/v1/users/{id}/deactivate` | Deactivate user | Admin |
| GET | `/app/v1/users/deleted/list` | List deleted users | Admin |
| POST | `/app/v1/users/{id}/restore` | Restore deleted user | Admin |

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |

## Usage Examples

### 1. Register a new user
```bash
curl -X POST http://localhost:8000/app/v1/users/signup \
  -H "Content-Type: application/json" \
  -d '{
    "username": "johndoe",
    "email": "john@example.com",
    "password": "Password@123",
    "full_name": "John Doe"
  }'
```

### 2. Login
```bash
curl -X POST http://localhost:8000/app/v1/users/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=johndoe&password=Password@123"
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": 2,
    "username": "johndoe",
    "email": "john@example.com",
    "full_name": "John Doe",
    "user_role": "user",
    "is_active": true,
    "disabled": false
  }
}
```

### 3. Get current user profile
```bash
curl -X GET http://localhost:8000/app/v1/users/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### 4. Update own profile
```bash
curl -X PUT http://localhost:8000/app/v1/users/2 \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "newemail@example.com",
    "full_name": "John Updated"
  }'
```

### 5. Admin - List all users
```bash
curl -X GET http://localhost:8000/app/v1/users/ \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN"
```

### 6. Admin - Reset user password
```bash
curl -X POST http://localhost:8000/app/v1/users/2/reset-password \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "new_password": "NewPass@123"
  }'
```

## Project Structure

```
GptMobal/
├── App/
│   ├── api/
│   │   ├── dependencies/
│   │   │   ├── auth.py          # JWT & password utilities
│   │   │   └── sqlite_connector.py
│   │   └── v1/
│   │       ├── Users.py         # User endpoints
│   │       └── langChainsRoutes.py
│   ├── core/
│   │   ├── settings.py          # Configuration
│   │   └── LoggingInit.py
│   ├── models/
│   │   └── userModels.py        # Pydantic models
│   ├── repository/
│   │   └── userRepository.py    # Database operations
│   └── schemas/
│       └── userSchemas.py
├── main.py                      # Application entry point
├── .env                         # Environment variables
└── app.db                       # SQLite database (auto-created)
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| SECRET_KEY | Yes | - | JWT secret key (min 32 chars) |
| ALGORITHM | Yes | HS256 | JWT algorithm |
| ACCESS_TOKEN_EXPIRE_MINUTES | Yes | 790 | Token expiry time |
| SQLITE_DATABASE_URL | Yes | sqlite:///./app.db | Database URL |
| LOG_FILEPATH | Yes | ./logs/ | Logs directory |
| RATE_LIMIT_DEFAULT | Yes | 100/minute | Rate limit |
| KILL_SWITCH_ENABLED | No | false | Maintenance mode |
| MEMORY_COST | Yes | 65536 | Argon2 memory cost |
| PARALLELISM | Yes | 2 | Argon2 parallelism |
| HASH_LENGTH | Yes | 32 | Argon2 hash length |
| SALT_LENGTH | Yes | 16 | Argon2 salt length |
| ADMIN_USERNAME | Yes | admin | Default admin username |
| ADMIN_EMAIL | Yes | admin@example.com | Default admin email |
| ADMIN_PASSWORD | Yes | Admin@123 | Default admin password |
| ENVIRONMENT | No | development | Environment mode |
| ALLOWED_ORIGINS | No | * | CORS origins |

## Production Deployment

1. Set `ENVIRONMENT=production` in `.env`
2. Set a strong `SECRET_KEY` (generate a random 64+ character string)
3. Configure `ALLOWED_ORIGINS` with your frontend domain
4. Use a production-grade database (PostgreSQL recommended)
5. Enable HTTPS/SSL
6. Configure proper CORS settings

## License

MIT License

## Author

**Talha Khalid**
