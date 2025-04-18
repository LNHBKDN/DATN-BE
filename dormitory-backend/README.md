# Dormitory Management System Backend

This is a Flask-based backend for a dormitory management system, supporting user authentication, room management, contracts, payments, reports, notifications, and more.

## Installation

1. **Clone the Repository**:
   ```bash
   git clone <repository_url>
   cd dormitory-backend
   ```

2. **Create and Activate a Virtual Environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set Up the Database**:
   - Create a MySQL database named `dormitory_db`.
   - Update `SQLALCHEMY_DATABASE_URI` in `config.py` with your MySQL credentials.
   - Initialize and apply migrations:
     ```bash
     flask db init
     flask db migrate -m "Initial migration"
     flask db upgrade
     ```

5. **Run the Application**:
   ```bash
   flask run
   ```
   The server will start at `http://127.0.0.1:5000`.

## API Usage

### Authentication
- **Login**: `POST /api/auth/login`
  - **Request Body**: `{ "email": "user@example.com", "password": "password" }`
  - **Response**: `{ "access_token": "jwt_token", "user_id": 1, "role": "USER" }`
  - **Description**: Authenticates a user and returns a JWT token.

- **Logout**: `POST /api/auth/logout`
  - **Headers**: `Authorization: Bearer <jwt_token>`
  - **Response**: `{ "message": "Logged out successfully" }`
  - **Description**: Logs out the user (client-side token removal).

### User Management
- **Get All Users (Admin)**: `GET /api/users`
  - **Headers**: `Authorization: Bearer <jwt_token>`
  - **Query Params**: `page=1&limit=10&role=USER&search=john`
  - **Response**: List of user objects (without passwords)
  - **Description**: Retrieves paginated list of users (Admin only).

- **Get Current User**: `GET /api/me`
  - **Headers**: `Authorization: Bearer <jwt_token>`
  - **Response**: Single user object (without password)
  - **Description**: Retrieves the profile of the logged-in user.

### Room Management
- **Get All Rooms**: `GET /api/rooms`
  - **Query Params**: `page=1&limit=10&min_capacity=2&max_capacity=8&available=true`
  - **Response**: List of room objects
  - **Description**: Retrieves rooms with filtering and pagination (public access).

- **Create Room (Admin)**: `POST /api/admin/rooms`
  - **Headers**: `Authorization: Bearer <jwt_token>`
  - **Request Body**: `{ "name": "Room 101", "capacity": 4, "price": 500000, "description": "Nice room" }`
  - **Response**: Newly created room object
  - **Description**: Creates a new room (Admin only).

*(Additional endpoints for other services like contracts, payments, etc., follow similar patterns as per the API list.)*

## Testing with Postman or curl

- **Login Example (curl)**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "admin123"}'
  ```

- **Get All Users (Postman)**:
  - Method: GET
  - URL: `http://127.0.0.1:5000/api/users?page=1&limit=10`
  - Headers: `Authorization: Bearer <jwt_token>`
  - Response: JSON list of users

*(Add similar examples for other key endpoints as needed.)*