from celery import Celery
from extensions import db
from app import create_app
from controllers.statistics_controller import save_user_room_snapshot, save_room_status_snapshot
from datetime import datetime

app = create_app()
celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

@celery.task
def run_snapshots():
    with app.app_context():
        current_time = datetime.utcnow()
        year = current_time.year
        month = current_time.month
        success_user = save_user_room_snapshot(year, month)
        success_room = save_room_status_snapshot(year, month)
        if success_user and success_room:
            print(f"Successfully ran snapshots for {year}-{month}")
        else:
            print(f"Failed to run snapshots for {year}-{month}")