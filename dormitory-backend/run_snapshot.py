# backend/run_room_snapshot.py
import sys
import os
from datetime import datetime

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from extensions import db
from app import app
from controllers.statistics_controller import save_room_status_snapshot

def run_room_snapshot(year, month):
    with app.app_context():
        print(f"Running room status snapshot for {year}-{month}")
        try:
            success = save_room_status_snapshot(target_year=year, target_month=month)
            if success:
                print(f"Successfully saved room status snapshot for {year}-{month}")
            else:
                print(f"Failed to save room status snapshot for {year}-{month}")
        except Exception as e:
            print(f"Error running room status snapshot: {str(e)}")

if __name__ == "__main__":
    # Snapshot for May 2025
    run_room_snapshot(year=2025, month=5)