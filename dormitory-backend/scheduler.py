from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from models.bill_detail import BillDetail
from models.service_rate import ServiceRate
from models.monthly_bill import MonthlyBill
from models.contract import Contract
from models.service import Service
from models.room import Room
from models.roomimage import RoomImage
from models.reportimage import ReportImage
from models.user import User
from models.register import Register
from dateutil.relativedelta import relativedelta
from extensions import db
import os
import logging
import pendulum
import shutil
from flask import current_app
import json
from controllers.statistics_controller import save_room_status_snapshot, save_user_room_snapshot

# Thiết lập logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_deleted_report_images():
    """Xóa các ảnh báo cáo đã bị xóa mềm sau 30 ngày."""
    logger.info("Starting cleanup_deleted_report_images")
    try:
        with current_app.app_context():
            threshold = datetime.utcnow() - timedelta(days=30)
            deleted_images = ReportImage.query.filter(
                ReportImage.is_deleted == True,
                ReportImage.deleted_at <= threshold
            ).all()

            for image in deleted_images:
                trash_path = os.path.join(current_app.config['UPLOAD_BASE'], 'trash', image.image_url)
                if os.path.exists(trash_path):
                    try:
                        os.remove(trash_path)
                        logger.info(f"Deleted file: {trash_path}")
                    except Exception as e:
                        logger.error(f"Error deleting file {trash_path}: {str(e)}")

                db.session.delete(image)

            db.session.commit()
            logger.info(f"Cleaned up {len(deleted_images)} deleted report images.")
    except Exception as e:
        with current_app.app_context():
            db.session.rollback()
            logger.error(f"Error during cleanup_deleted_report_images: {str(e)}", exc_info=True)

def update_bill_details_job():
    """Cập nhật chi tiết hóa đơn cho tháng hiện tại."""
    logger.info("Starting update_bill_details_job")
    try:
        with current_app.app_context():
            today = datetime.date.today()
            current_month = today.replace(day=1)
            previous_month = current_month - relativedelta(months=1)

            services = Service.query.all()
            if not services:
                logger.error("No services found")
                return

            rooms = Room.query.all()
            for room in rooms:
                for service in services:
                    rate = ServiceRate.query.filter(
                        ServiceRate.service_id == service.service_id,
                        ServiceRate.effective_date <= today
                    ).order_by(ServiceRate.effective_date.desc()).first()

                    if not rate:
                        logger.warning(f"No rate found for service {service.name} on {today}")
                        continue

                    existing_detail = BillDetail.query.filter_by(
                        room_id=room.room_id,
                        bill_month=current_month,
                        rate_id=rate.rate_id
                    ).first()
                    if existing_detail:
                        continue

                    previous_detail = BillDetail.query.filter_by(
                        room_id=room.room_id,
                        bill_month=previous_month,
                        rate_id=rate.rate_id
                    ).first()

                    previous_reading = previous_detail.current_reading if previous_detail else 0.0

                    new_detail = BillDetail(
                        rate_id=rate.rate_id,
                        previous_reading=previous_reading,
                        current_reading=0.0,
                        price=0.0,
                        room_id=room.room_id,
                        bill_month=current_month
                    )
                    db.session.add(new_detail)

            db.session.commit()
            logger.info("update_bill_details_job completed successfully")
    except Exception as e:
        with current_app.app_context():
            db.session.rollback()
            logger.error(f"Error in update_bill_details_job: {str(e)}", exc_info=True)

def cleanup_deleted_rooms():
    """Xóa cứng các phòng đã bị xóa mềm sau 30 ngày."""
    logger.info("Starting cleanup_deleted_rooms")
    try:
        with current_app.app_context():
            threshold = datetime.utcnow() - timedelta(days=30)
            deleted_rooms = Room.query.filter(
                Room.is_deleted == True,
                Room.deleted_at <= threshold
            ).all()

            for room in deleted_rooms:
                db.session.delete(room)
                logger.info(f"Permanently deleted room: room_id={room.room_id}")

            db.session.commit()
            logger.info(f"Cleaned up {len(deleted_rooms)} deleted rooms.")
    except Exception as e:
        with current_app.app_context():
            db.session.rollback()
            logger.error(f"Error during cleanup_deleted_rooms: {str(e)}", exc_info=True)

def cleanup_deleted_contracts():
    """Xóa cứng các hợp đồng đã bị xóa mềm sau 30 ngày."""
    logger.info("Starting cleanup_deleted_contracts")
    try:
        with current_app.app_context():
            threshold = datetime.utcnow() - timedelta(days=30)
            deleted_contracts = Contract.query.filter(
                Contract.is_deleted == True,
                Contract.deleted_at <= threshold
            ).all()

            for contract in deleted_contracts:
                db.session.delete(contract)
                logger.info(f"Permanently deleted contract: contract_id={contract.id}")

            db.session.commit()
            logger.info(f"Cleaned up {len(deleted_contracts)} deleted contracts.")
    except Exception as e:
        with current_app.app_context():
            db.session.rollback()
            logger.error(f"Error during cleanup_deleted_contracts: {str(e)}", exc_info=True)

def cleanup_deleted_images():
    """Xóa các ảnh phòng đã bị xóa mềm sau 30 ngày."""
    logger.info("Starting cleanup_deleted_images")
    try:
        with current_app.app_context():
            threshold = datetime.utcnow() - timedelta(days=30)
            deleted_images = RoomImage.query.filter(
                RoomImage.is_deleted == True,
                RoomImage.deleted_at <= threshold
            ).all()

            for image in deleted_images:
                trash_path = os.path.join(current_app.config['UPLOAD_BASE'], 'trash', image.image_url)
                if os.path.exists(trash_path):
                    try:
                        os.remove(trash_path)
                        logger.info(f"Deleted file: {trash_path}")
                    except Exception as e:
                        logger.error(f"Error deleting file {trash_path}: {str(e)}")

                db.session.delete(image)

            db.session.commit()
            logger.info(f"Cleaned up {len(deleted_images)} deleted images.")
    except Exception as e:
        with current_app.app_context():
            db.session.rollback()
            logger.error(f"Error during cleanup_deleted_images: {str(e)}", exc_info=True)

def update_previous_readings_job(app):
    """Cập nhật previous_reading cho các hóa đơn tháng hiện tại."""
    logger.info("Starting update_previous_readings_job")
    try:
        with app.app_context():
            today = datetime.today().date()
            current_month = today.replace(day=1)
            previous_month = current_month - relativedelta(months=1)

            services = Service.query.all()
            if not services:
                logger.info("Không tìm thấy dịch vụ nào")
                return

            default_reading = {service.name.lower(): 0.0 for service in services}

            rooms = Room.query.all()
            for room in rooms:
                previous_detail = BillDetail.query.filter_by(
                    room_id=room.room_id,
                    bill_month=previous_month
                ).first()

                current_detail = BillDetail.query.filter_by(
                    room_id=room.room_id,
                    bill_month=current_month
                ).first()

                if current_detail:
                    continue

                if previous_detail:
                    new_previous_reading = previous_detail.current_reading
                else:
                    new_previous_reading = json.dumps(default_reading)

                new_detail = BillDetail(
                    bill_month=current_month,
                    previous_reading=new_previous_reading,
                    current_reading=json.dumps(default_reading),
                    price=0.0,
                    submitted_by=None,
                    room_id=room.room_id
                )
                db.session.add(new_detail)

            db.session.commit()
            logger.info(f"Cập nhật previous_reading thành công vào {today}")
    except Exception as e:
        with app.app_context():
            db.session.rollback()
            logger.error(f"Error in update_previous_readings_job: {str(e)}", exc_info=True)

def update_contract_status():
    """Cập nhật trạng thái cho các hợp đồng có khả năng thay đổi trạng thái."""
    logger.info("Starting update_contract_status")
    try:
        with current_app.app_context():
            now = pendulum.now('Asia/Ho_Chi_Minh').date()
            window_start = now - timedelta(hours=2)
            window_end = now + timedelta(hours=2)

            contracts = Contract.query.filter(
                (
                    (Contract.start_date >= window_start) & (Contract.start_date <= window_end)
                ) | (
                    (Contract.end_date >= window_start) & (Contract.end_date <= window_end)
                ) | (
                    Contract.status.in_(['PENDING', 'ACTIVE'])
                )
            ).all()

            updated_count = 0
            for contract in contracts:
                try:
                    if not contract.start_date or not contract.end_date:
                        logger.warning(f"Contract {contract.contract_id} has invalid start_date or end_date")
                        continue
                    old_status = contract.status
                    contract.update_status()
                    if old_status != contract.status:
                        updated_count += 1
                        logger.debug(f"Updated contract {contract.contract_id} status from {old_status} to {contract.status}")
                except Exception as e:
                    logger.error(f"Error updating contract {contract.contract_id}: {str(e)}")
                    continue

            db.session.commit()
            logger.info(f"Updated status for {updated_count} contracts")
    except Exception as e:
        with current_app.app_context():
            db.session.rollback()
            logger.error(f"Error during update_contract_status: {str(e)}", exc_info=True)

def cleanup_deleted_avatars():
    """Xóa ảnh avatar trong thư mục trash sau 30 ngày."""
    logger.info("Starting cleanup_deleted_avatars")
    try:
        with current_app.app_context():
            threshold = datetime.utcnow() - timedelta(days=30)
            users = User.query.filter(
                User.avatar_url.isnot(None),
                User.is_deleted == True,
                User.deleted_at <= threshold
            ).all()

            for user in users:
                if user.avatar_url:
                    trash_path = os.path.join(current_app.config['TRASH_BASE'], f"{datetime.utcnow().timestamp()}_{os.path.basename(user.avatar_url)}")
                    if os.path.exists(trash_path):
                        try:
                            os.remove(trash_path)
                            logger.info(f"Deleted avatar from trash: {trash_path}")
                        except Exception as e:
                            logger.error(f"Error deleting avatar {trash_path}: {str(e)}")
                    user.avatar_url = None
                    db.session.add(user)

            db.session.commit()
            logger.info(f"Cleaned up {len(users)} deleted avatars.")
    except Exception as e:
        with current_app.app_context():
            db.session.rollback()
            logger.error(f"Error during cleanup_deleted_avatars: {str(e)}", exc_info=True)

def delete_old_paid_bills():
    """Xóa các MonthlyBill đã thanh toán và BillDetail liên quan, cũ hơn 6 tháng."""
    logger.info("Starting delete_old_paid_bills")
    try:
        with current_app.app_context():
            cutoff_date = datetime.now().date() - timedelta(days=180)

            paid_bills = MonthlyBill.query.filter(
                MonthlyBill.payment_status == 'PAID',
                MonthlyBill.bill_month < cutoff_date
            ).all()

            if not paid_bills:
                logger.info("No old paid bills found to delete")
                return

            deleted_bill_ids = []
            deleted_detail_ids = []

            for bill in paid_bills:
                detail_id = bill.detail_id
                deleted_bill_ids.append(bill.bill_id)
                db.session.delete(bill)

                bill_detail = BillDetail.query.get(detail_id)
                if bill_detail:
                    deleted_detail_ids.append(detail_id)
                    db.session.delete(bill_detail)

            db.session.commit()
            logger.info(f"Deleted old MonthlyBills: {deleted_bill_ids}, BillDetails: {deleted_detail_ids}")
    except Exception as e:
        with current_app.app_context():
            db.session.rollback()
            logger.error(f"Error in delete_old_paid_bills: {str(e)}", exc_info=True)

def cleanup_deleted_registrations():
    """Xóa cứng các đăng ký đã bị xóa mềm sau 30 ngày."""
    logger.info("Starting cleanup_deleted_registrations")
    try:
        with current_app.app_context():
            threshold = datetime.utcnow() - timedelta(days=30)
            deleted_registrations = Register.query.filter(
                Register.is_deleted == True,
                Register.deleted_at <= threshold
            ).all()

            for registration in deleted_registrations:
                db.session.delete(registration)
                logger.info(f"Permanently deleted registration: registration_id={registration.id}")

            db.session.commit()
            logger.info(f"Cleaned up {len(deleted_registrations)} deleted registrations.")
    except Exception as e:
        with current_app.app_context():
            db.session.rollback()
            logger.error(f"Error during cleanup_deleted_registrations: {str(e)}", exc_info=True)

def cleanup_trash_folder():
    """Xóa tất cả các file và thư mục trong thư mục trash vào ngày 31/12 hàng năm."""
    logger.info("Starting cleanup_trash_folder")
    try:
        with current_app.app_context():
            trash_path = current_app.config['TRASH_BASE']

            if not os.path.exists(trash_path):
                logger.info(f"Trash folder does not exist: {trash_path}")
                return

            deleted_files = 0
            deleted_dirs = 0
            for root, dirs, files in os.walk(trash_path, topdown=False):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        os.remove(file_path)
                        logger.info(f"Deleted file from trash: {file_path}")
                        deleted_files += 1
                    except Exception as e:
                        logger.error(f"Error deleting file {file_path}: {str(e)}")

                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    try:
                        shutil.rmtree(dir_path)
                        logger.info(f"Deleted directory from trash: {dir_path}")
                        deleted_dirs += 1
                    except Exception as e:
                        logger.error(f"Error deleting directory {dir_path}: {str(e)}")

            logger.info(f"Cleaned up {deleted_files} files and {deleted_dirs} directories from trash folder")
    except Exception as e:
        with current_app.app_context():
            logger.error(f"Error during cleanup_trash_folder: {str(e)}", exc_info=True)

def init_scheduler(app):
    """Khởi tạo scheduler với các tác vụ theo lịch trình."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        cleanup_deleted_avatars,
        'cron',
        hour=2,
        minute=0
    )
    scheduler.add_job(
        lambda: update_previous_readings_job(app),
        'cron',
        day=1,
        hour=0,
        minute=0
    )
    scheduler.add_job(
        delete_old_paid_bills,
        'cron',
        day=1,
        hour=0,
        minute=0
    )
    scheduler.add_job(
        cleanup_deleted_report_images,
        'cron',
        hour=2,
        minute=0
    )
    scheduler.add_job(
        cleanup_deleted_images,
        'cron',
        hour=2,
        minute=0
    )
    scheduler.add_job(
        update_contract_status,
        'interval',
        hours=2
    )
    scheduler.add_job(
        update_bill_details_job,
        'cron',
        day=1,
        hour=0,
        minute=0
    )
    scheduler.add_job(
        cleanup_deleted_rooms,
        'cron',
        hour=2,
        minute=0
    )
    scheduler.add_job(
        cleanup_deleted_contracts,
        'cron',
        hour=2,
        minute=0
    )
    scheduler.add_job(
        cleanup_deleted_registrations,
        'cron',
        hour=2,
        minute=0
    )
    scheduler.add_job(
        cleanup_trash_folder,
        'cron',
        month=12,
        day=31,
        hour=0,
        minute=0
    )
    scheduler.add_job(
        save_room_status_snapshot,
        'cron',
        day='last',
        hour=23,
        minute=59
    )
    scheduler.add_job(
        save_user_room_snapshot,
        'cron',
        day='last',
        hour=23,
        minute=59
    )
    scheduler.start()
    logger.info("Scheduler initialized for cleanup tasks.")