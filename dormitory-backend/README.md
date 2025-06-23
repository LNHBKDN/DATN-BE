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
     or
     python -m flask db upgrade
     ```

5. **Run the Application**:
   ```bash
   flask run
   ```
   The server will start at `http://127.0.0.1:5000`.

## PDF Export Setup (WeasyPrint on Windows)

To enable PDF export (contract export) using WeasyPrint, you must install additional system libraries on Windows:

1. **Install WeasyPrint Python package:**
   ```
   pip install WeasyPrint
   ```
2. **Install GTK3 Runtime:**
   - Download the latest GTK3 runtime installer from: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
   - Run the installer and complete the installation. Note the install path (e.g., `C:\Program Files\GTK3-Runtime Win64\bin`).
3. **Add GTK3 to your system PATH:**
   - Open "Edit the system environment variables" > "Environment Variables".
   - Under "System variables", select "Path" and click "Edit".
   - Add the GTK3 `bin` path (e.g., `C:\Program Files\GTK3-Runtime Win64\bin`).
   - Click OK to save.
4. **Restart your computer or terminal.**

