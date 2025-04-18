from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime,  timedelta 
from models.bill_detail import BillDetail
from models.service_rate import ServiceRate
from models.monthly_bill import MonthlyBill
from models.bill_detail import BillDetail
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from models.room import Room
from models.service import Service
from models.roomimage import RoomImage
from models.reportimage import ReportImage
import json
from dateutil.relativedelta import relativedelta
from extensions import db
import os
def cleanup_deleted_report_images():
    try:
        # Lấy các ảnh đã bị xóa (is_deleted=True) và deleted_at trước 24 giờ
        threshold = datetime.utcnow() - timedelta(days=30)  # Xóa sau 1 ngày
        deleted_images = ReportImage.query.filter(
            ReportImage.is_deleted == True,
            ReportImage.deleted_at <= threshold
        ).all()

        for image in deleted_images:
            # Xóa file trong thư mục rác
            trash_path = os.path.join(current_app.config['UPLOAD_BASE'], 'trash', image.image_url)
            if os.path.exists(trash_path):
                try:
                    os.remove(trash_path)
                except Exception as e:
                    print(f"Error deleting file {trash_path}: {str(e)}")

            # Xóa bản ghi khỏi cơ sở dữ liệu
            db.session.delete(image)

        try:
            db.session.commit()
            print(f"Cleaned up {len(deleted_images)} deleted report images.")
        except Exception as e:
            db.session.rollback()
            print(f"Error committing cleanup: {str(e)}")

    except Exception as e:
        print(f"Error during cleanup: {str(e)}")
def update_bill_details_job():
    logging.info("Running update_bill_details_job")
    try:
        with app.app_context():
            today = date.today()
            current_month = today.replace(day=1)
            previous_month = current_month - relativedelta(months=1)

            services = Service.query.all()
            if not services:
                logging.error("No services found")
                return

            rooms = Room.query.all()
            for room in rooms:
                for service in services:
                    # Kiểm tra xem đã có BillDetail cho tháng hiện tại chưa
                    existing_detail = BillDetail.query.filter_by(
                        room_id=room.room_id,
                        bill_month=current_month,
                        rate_id=ServiceRate.query.filter(
                            ServiceRate.service_id == service.service_id,
                            ServiceRate.effective_date <= current_month
                        ).order_by(ServiceRate.effective_date.desc()).first().rate_id
                    ).first()
                    if existing_detail:
                        continue

                    # Lấy mức giá hiện tại
                    rate = ServiceRate.query.filter(
                        ServiceRate.service_id == service.service_id,
                        ServiceRate.effective_date <= current_month
                    ).order_by(ServiceRate.effective_date.desc()).first()

                    if not rate:
                        logging.warning(f"No rate found for service {service.name} on {current_month}")
                        continue

                    # Lấy current_reading của tháng trước
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
            logging.info("update_bill_details_job completed successfully")

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in update_bill_details_job: {str(e)}")
def cleanup_deleted_images():
    try:
        # Lấy các ảnh đã bị xóa (is_deleted=True) và deleted_at trước xxxx giờ
        threshold = datetime.utcnow() - timedelta(days=30)  # Xóa sau 100 ngày
        deleted_images = RoomImage.query.filter(
            RoomImage.is_deleted == True,
            RoomImage.deleted_at <= threshold
        ).all()

        for image in deleted_images:
            # Xóa file trong thư mục rác
            trash_path = os.path.join(current_app.config['UPLOAD_BASE'], 'trash', image.image_url)
            if os.path.exists(trash_path):
                try:
                    os.remove(trash_path)
                except Exception as e:
                    print(f"Error deleting file {trash_path}: {str(e)}")

            # Xóa bản ghi khỏi cơ sở dữ liệu
            db.session.delete(image)

        try:
            db.session.commit()
            print(f"Cleaned up {len(deleted_images)} deleted images.")
        except Exception as e:
            db.session.rollback()
            print(f"Error committing cleanup: {str(e)}")

    except Exception as e:
        print(f"Error during cleanup: {str(e)}")
def update_previous_readings_job(db):
    with db.app.app_context():  # Đảm bảo chạy trong context của Flask
        today = datetime.today().date()
        current_month = today.replace(day=1)  # Ngày 1 của tháng hiện tại
        previous_month = current_month - relativedelta(months=1)  # Ngày 1 của tháng trước

        # Lấy danh sách dịch vụ
        services = Service.query.all()
        if not services:
            print("Không tìm thấy dịch vụ nào")
            return

        # Tạo giá trị mặc định cho previous_reading và current_reading
        default_reading = {service.name.lower(): 0.0 for service in services}

        # Lấy tất cả phòng
        rooms = Room.query.all()
        for room in rooms:
            # Lấy BillDetail của tháng trước
            previous_detail = BillDetail.query.filter_by(
                room_id=room.room_id,
                bill_month=previous_month
            ).first()

            # Kiểm tra xem đã có BillDetail cho tháng hiện tại chưa
            current_detail = BillDetail.query.filter_by(
                room_id=room.room_id,
                bill_month=current_month
            ).first()

            if current_detail:
                continue  # Nếu đã có BillDetail cho tháng hiện tại, bỏ qua

            # Nếu có BillDetail của tháng trước, lấy current_reading để làm previous_reading
            if previous_detail:
                new_previous_reading = previous_detail.current_reading
            else:
                new_previous_reading = json.dumps(default_reading)

            # Tạo BillDetail mới cho tháng hiện tại
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
        print(f"Cập nhật previous_reading thành công vào {today}")
def update_contract_status():
    """Cập nhật trạng thái cho tất cả hợp đồng."""
    try:
        with current_app.app_context():
            contracts = Contract.query.all()
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
                    continue  # Tiếp tục với hợp đồng khác
            db.session.commit()
            logger.info(f"Updated status for {updated_count} contracts")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error during contract status update: {str(e)}")
def cleanup_deleted_avatars():
    """Xóa ảnh avatar trong thư mục trash sau 30 ngày."""
    try:
        with current_app.app_context():
            # Tìm các user có avatar_url cũ (do thay đổi avatar)
            threshold = datetime.utcnow() - timedelta(days=30)
            users = User.query.filter(
                User.avatar_url.isnot(None),
                User.is_deleted == True,
                User.deleted_at <= threshold
            ).all()

            for user in users:
                if user.avatar_url:
                    trash_path = os.path.join(current_app.config['TRASH_BASE'], f"{datetime.utcnow().timestamp()}_{filename}")
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
        db.session.rollback()
        logger.error(f"Error during avatar cleanup: {str(e)}")
def delete_old_paid_bills():
    """Xóa các MonthlyBill đã thanh toán và BillDetail liên quan, cũ hơn 6 tháng."""
    try:
        # Tính ngày giới hạn (6 tháng trước)
        cutoff_date = datetime.now().date() - timedelta(days=180)

        # Tìm các MonthlyBill đã thanh toán và cũ hơn 6 tháng
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

            # Xóa MonthlyBill
            deleted_bill_ids.append(bill.bill_id)
            db.session.delete(bill)

            # Xóa BillDetail liên quan
            bill_detail = BillDetail.query.get(detail_id)
            if bill_detail:
                deleted_detail_ids.append(detail_id)
                db.session.delete(bill_detail)

        db.session.commit()
        logger.info(f"Deleted old MonthlyBills: {deleted_bill_ids}, BillDetails: {deleted_detail_ids}")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in delete_old_paid_bills: {str(e)}")
def init_scheduler(db):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        cleanup_deleted_avatars,
        'cron',
        hour=2,
        minute=0
    )
    # Lập lịch chạy update_previous_readings_job vào ngày 1 hàng tháng, lúc 00:00
    scheduler.add_job(
        lambda: update_previous_readings_job(db),
        'cron',
        day=1,
        hour=0,
        minute=0
    )
    scheduler.add_job(delete_old_paid_bills, 'cron', day=1, hour=0, minute=0)
    # Lập lịch chạy cleanup_deleted_report_images vào 2:00 sáng mỗi ngày
    scheduler.add_job(
        cleanup_deleted_report_images,
        'cron',
        hour=2,
        minute=0
    )
    
    # Lập lịch chạy cleanup_deleted_images vào 2:00 sáng mỗi ngày
    scheduler.add_job(
        cleanup_deleted_images,
        'cron',
        hour=2,
        minute=0
    )
    # Lập lịch chạy update_contract_status vào 2:00 sáng mỗi ngày
    scheduler.add_job(
        update_contract_status,
        'cron',
        hour=2,
        minute=0
    )
    scheduler.add_job(update_bill_details_job, 'cron', day=1, hour=0, minute=0)
    scheduler.start()
    print("Scheduler initialized for cleanup tasks.")