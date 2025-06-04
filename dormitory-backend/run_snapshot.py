import sys
import os
import argparse
import pendulum
from datetime import datetime

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from extensions import db
from app import app
from controllers.statistics_controller import snapshot_room_status
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_room_snapshot(year=None, month=None):
    with app.app_context():
        current_time = pendulum.now('Asia/Ho_Chi_Minh')
        year = year or current_time.year
        month = month or current_time.month
        logger.info(f"Running room status snapshot for {year}-{month}")
        try:
            success = snapshot_room_status(year=year, month=month)
            if success:
                print(f"Successfully saved room status snapshot for {year}-{month}")
                logger.info(f"Successfully saved room status snapshot for {year}-{month}")
            else:
                print(f"Failed to save room status snapshot for {year}-{month}")
                logger.error(f"Failed to save room status snapshot for {year}-{month}")
        except Exception as e:
            print(f"Error running room status snapshot: {str(e)}")
            logger.error(f"Error running room status snapshot for {year}-{month}: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run room status snapshot")
    parser.add_argument('--year', type=int, help="Year for snapshot (default: current year)")
    parser.add_argument('--month', type=int, help="Month for snapshot (default: current month)")
    args = parser.parse_args()
    
    run_room_snapshot(year=args.year, month=args.month)