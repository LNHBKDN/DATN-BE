from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from models.monthly_bill import MonthlyBill
from models.bill_detail import BillDetail
from models.user import User
from models.room import Room
from models.service import Service
from models.service_rate import ServiceRate
from models.contract import Contract
from models.notification import Notification
from models.notification_recipient import NotificationRecipient
from controllers.auth_controller import admin_required, user_required
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from sqlalchemy.exc import IntegrityError
from datetime import timedelta
import logging
from decimal import Decimal

from utils.fcm import send_fcm_notification
logging.basicConfig(level=logging.DEBUG)

monthly_bill_bp = Blueprint('monthly_bill', __name__)

# Utility function to get active room_id from user_id via Contract
def get_active_room_id(user_id):
    contract = Contract.query.filter_by(user_id=user_id, status='ACTIVE').first()
    if not contract:
        return None
    return contract.room_id

@monthly_bill_bp.route('/bill-details', methods=['POST'])
@user_required()
def submit_bill_detail():
    logging.debug(f"POST /bill-details with data: {request.get_json()}")
    try:
        identity = get_jwt_identity()
        try:
            user_id = identity['id'] if isinstance(identity, dict) else int(identity)
        except (TypeError, ValueError) as e:
            logging.error(f"Invalid identity format: {str(e)}")
            return jsonify({'message': 'Token không hợp lệ', 'error': str(e)}), 401

        # Get room_id from active contract
        room_id = get_active_room_id(user_id)
        if not room_id:
            return jsonify({'message': 'Bạn không có hợp đồng hoạt động nào'}), 403

        room = Room.query.get(room_id)
        if not room:
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        user = User.query.get(user_id)
        if not user or not any(contract.room_id == room_id and contract.status == 'ACTIVE' for contract in user.contracts):
            return jsonify({'message': 'Bạn không có quyền gửi chỉ số cho phòng này'}), 403

        try:
            data = request.get_json()
        except Exception:
            logging.error("Invalid JSON data")
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

        bill_month = data.get('bill_month')
        readings = data.get('readings')

        if not bill_month or not readings:
            return jsonify({'message': 'Vui lòng cung cấp tháng hóa đơn và chỉ số'}), 400

        # Parse bill_month (YYYY-MM)
        try:
            bill_month_date = datetime.strptime(bill_month + '-01', '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'message': 'Định dạng bill_month không hợp lệ (YYYY-MM)'}), 400

        # Kiểm tra tháng hiện tại đã có bản ghi chưa
        current_month = datetime.now().date().replace(day=1)
        existing_current_month_detail = BillDetail.query.filter_by(
            room_id=room_id,
            bill_month=current_month
        ).first()
        if existing_current_month_detail and bill_month_date < current_month:
            return jsonify({'message': f'Không thể gửi chỉ số cho tháng {bill_month} vì tháng hiện tại ({current_month.strftime("%Y-%m")}) đã có bản ghi'}), 409

        services = Service.query.all()
        if not services:
            return jsonify({'message': 'Không tìm thấy dịch vụ nào'}), 404

        valid_service_ids = {str(service.service_id) for service in services}
        logging.debug(f"Valid service IDs: {valid_service_ids}")

        last_day_of_bill_month = bill_month_date + relativedelta(months=1) - relativedelta(days=1)
        logging.debug(f"Selecting rate for bill_month {bill_month_date}, last day of month: {last_day_of_bill_month}")

        for service_id in readings:
            if service_id not in valid_service_ids:
                return jsonify({'message': f'ID dịch vụ {service_id} không hợp lệ'}), 400

            rate = ServiceRate.query.filter(
                ServiceRate.service_id == int(service_id),
                ServiceRate.effective_date <= last_day_of_bill_month
            ).order_by(ServiceRate.effective_date.desc()).first()

            if not rate:
                return jsonify({'message': f'Không tìm thấy mức giá hiện tại cho dịch vụ ID {service_id}'}), 404

            logging.debug(f"Selected rate for service_id {service_id}: {rate.to_dict()}")

            existing_detail = BillDetail.query.filter_by(
                room_id=room_id,
                bill_month=bill_month_date,
                rate_id=rate.rate_id
            ).first()
            if existing_detail:
                return jsonify({'message': f'Đã có người gửi chỉ số cho dịch vụ ID {service_id} trong tháng này'}), 409

        try:
            bill_details = []
            previous_month = bill_month_date - relativedelta(months=1)

            for service_id in readings:
                service = Service.query.get(int(service_id))
                if not service:
                    return jsonify({'message': f'Không tìm thấy dịch vụ ID {service_id}'}), 404

                logging.debug(f"Processing service_id: {service_id}, service name: {service.name}")

                if not isinstance(readings[service_id], dict):
                    return jsonify({'message': f'Chỉ số cho dịch vụ ID {service_id} ({service.name}) phải là một object'}), 400

                current = readings[service_id].get('current')
                if current is None:
                    return jsonify({'message': f'Vui lòng nhập chỉ số hiện tại cho dịch vụ ID {service_id} ({service.name})'}), 400

                try:
                    current = float(current)
                except (TypeError, ValueError):
                    return jsonify({'message': f'Chỉ số hiện tại cho dịch vụ ID {service_id} ({service.name}) phải là số hợp lệ'}), 400

                if current < 0:
                    return jsonify({'message': f'Chỉ số hiện tại cho dịch vụ ID {service_id} ({service.name}) không được âm'}), 400

                with db.session.no_autoflush:
                    previous_detail = BillDetail.query.join(ServiceRate).filter(
                        BillDetail.room_id == room_id,
                        BillDetail.bill_month == previous_month,
                        ServiceRate.service_id == service.service_id
                    ).order_by(BillDetail.submitted_at.desc()).first()

                previous = float(previous_detail.current_reading) if previous_detail else 0.0

                if current < previous:
                    return jsonify({'message': f'Chỉ số hiện tại phải lớn hơn hoặc bằng chỉ số trước đó ({previous}) cho dịch vụ ID {service_id} ({service.name})'}), 400

                rate = ServiceRate.query.filter(
                    ServiceRate.service_id == service.service_id,
                    ServiceRate.effective_date <= last_day_of_bill_month
                ).order_by(ServiceRate.effective_date.desc()).first()

                if not rate:
                    return jsonify({'message': f'Không tìm thấy mức giá hiện tại cho dịch vụ ID {service_id} ({service.name})'}), 404

                logging.debug(f"Final selected rate for service_id {service_id}: {rate.to_dict()}")

                if service.service_id in [1, 2]:
                    usage = current - previous
                    price = usage * float(rate.unit_price)
                else:
                    price = float(rate.unit_price)

                bill_detail = BillDetail(
                    rate_id=rate.rate_id,
                    previous_reading=previous,
                    current_reading=current,
                    price=price,
                    room_id=room_id,
                    bill_month=bill_month_date,
                    submitted_by=user_id
                )
                bill_details.append(bill_detail)
                db.session.add(bill_detail)

            db.session.commit()

            try:
                service_names = [Service.query.get(int(service_id)).name for service_id in readings]
                notification = Notification(
                    title="Gửi chỉ số thành công",
                    message=f"Bạn đã gửi chỉ số cho tháng {bill_month_date.strftime('%Y-%m')} của các dịch vụ ({', '.join(service_names)}) thành công.",
                    target_type="SYSTEM",
                    target_id=user_id,
                    related_entity_type="BILL_DETAIL",
                    related_entity_id=bill_details[0].detail_id if bill_details else None,
                    created_at=datetime.utcnow()
                )
                db.session.add(notification)
                db.session.flush()
                recipient = NotificationRecipient(
                    notification_id=notification.id,
                    user_id=user_id,
                    is_read=False
                )
                db.session.add(recipient)
                send_fcm_notification(
                    user_id=user_id,
                    title=notification.title,
                    message=notification.message,
                    data={
                        'notification_id': str(notification.id),
                        'related_entity_type': 'BILL_DETAIL',
                        'related_entity_id': str(bill_details[0].detail_id) if bill_details else ''
                    }
                )
                db.session.commit()
                logging.info(f"Notification created for user {user_id}, notification_id={notification.id}")
            except Exception as e:
                db.session.rollback()
                logging.error(f"Failed to create SYSTEM notification for user {user_id}: {str(e)}")

            return jsonify({'message': 'Đã nộp chỉ số thành công'}), 201

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in submit_bill_detail: {str(e)}")
            return jsonify({'message': 'Lỗi khi gửi chỉ số', 'error': str(e)}), 500

    except Exception as e:
        logging.error(f"Error in submit_bill_detail: {str(e)}")
        return jsonify({'message': 'Lỗi khi gửi chỉ số', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/monthly-bills/bulk', methods=['POST'])
@admin_required()
def create_monthly_bills_bulk():
    logging.debug(f"POST /admin/monthly-bills/bulk with data: {request.get_json()}")
    try:
        try:
            data = request.get_json()
        except Exception:
            logging.error("Invalid JSON data")
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

        bill_month = data.get('bill_month')
        room_ids = data.get('room_ids')

        if not bill_month:
            logging.error("Missing bill_month in request")
            return jsonify({'message': 'Yêu cầu bill_month'}), 400

        try:
            bill_month_date = datetime.strptime(bill_month + '-01', '%Y-%m-%d').date()
        except ValueError:
            logging.error(f"Invalid bill_month format: {bill_month}")
            return jsonify({'message': 'Định dạng bill_month không hợp lệ (YYYY-MM)'}), 400

        logging.debug(f"Processing bill_month: {bill_month_date}, room_ids: {room_ids}")

        if room_ids:
            rooms = Room.query.filter(Room.room_id.in_(room_ids)).all()
            if len(rooms) != len(room_ids):
                invalid_ids = set(room_ids) - set(room.room_id for room in rooms)
                logging.error(f"Rooms not found for IDs: {invalid_ids}")
                return jsonify({'message': f'Không tìm thấy phòng với ID: {invalid_ids}'}), 404
        else:
            rooms = Room.query.all()

        if not rooms:
            logging.error("No rooms found")
            return jsonify({'message': 'Không tìm thấy phòng nào'}), 404

        logging.debug(f"Found {len(rooms)} rooms to process")

        new_bills = []
        errors = []

        today = datetime.today().date()

        try:
            for room in rooms:
                room_id = room.room_id
                logging.debug(f"Processing room_id: {room_id}")

                bill_details = BillDetail.query.filter(
                    BillDetail.room_id == room_id,
                    BillDetail.bill_month == bill_month_date,
                    ~BillDetail.detail_id.in_(
                        db.session.query(MonthlyBill.detail_id).filter(MonthlyBill.bill_month == bill_month_date)
                    )
                ).all()

                if not bill_details:
                    logging.debug(f"No unlinked bill details found for room_id {room_id}, bill_month {bill_month_date}")
                    errors.append({
                        'room_id': room_id,
                        'error': 'Không tìm thấy chỉ số dịch vụ chưa liên kết cho tháng này'
                    })
                    continue

                logging.debug(f"Found {len(bill_details)} bill details for room_id {room_id}")

                contract = next(
                    (c for c in room.contracts if c.status == 'ACTIVE' and c.user_id),
                    None
                )
                if not contract:
                    logging.debug(f"No active contract found for room_id {room_id}")
                    errors.append({
                        'room_id': room_id,
                        'error': 'Không tìm thấy hợp đồng hoạt động cho phòng'
                    })
                    continue

                user_id = contract.user_id
                user = User.query.get(user_id)
                if not user:
                    logging.debug(f"User not found for user_id {user_id}")
                    errors.append({
                        'room_id': room_id,
                        'error': f'Không tìm thấy người dùng với ID {user_id}'
                    })
                    continue

                logging.debug(f"Processing for user_id: {user_id}")

                for detail in bill_details:
                    service_rate = ServiceRate.query.get(detail.rate_id)
                    if not service_rate:
                        logging.debug(f"Service rate not found for detail_id {detail.detail_id}")
                        errors.append({
                            'room_id': room_id,
                            'error': f'Không tìm thấy mức giá liên quan đến chi tiết hóa đơn với detail_id {detail.detail_id}'
                        })
                        continue

                    service = Service.query.get(service_rate.service_id)
                    if not service:
                        logging.debug(f"Service not found for service_id {service_rate.service_id}")
                        errors.append({
                            'room_id': room_id,
                            'error': f'Không tìm thấy dịch vụ liên quan đến chi tiết hóa đơn với detail_id {detail.detail_id}'
                        })
                        continue

                    rate = ServiceRate.query.filter(
                        ServiceRate.service_id == service.service_id,
                        ServiceRate.effective_date <= today
                    ).order_by(ServiceRate.effective_date.desc()).first()

                    if rate:
                        usage = float(detail.current_reading) - float(detail.previous_reading)
                        unit_price = float(rate.unit_price)
                        detail.price = usage * unit_price
                        detail.rate_id = rate.rate_id
                        db.session.add(detail)
                        logging.debug(f"Updated bill detail {detail.detail_id} with price {detail.price}")

                    existing_bill = MonthlyBill.query.filter_by(
                        room_id=room_id,
                        bill_month=bill_month_date,
                        detail_id=detail.detail_id
                    ).first()
                    if existing_bill:
                        logging.debug(f"Bill already exists for detail_id {detail.detail_id}, room_id {room_id}, bill_month {bill_month_date}")
                        errors.append({
                            'room_id': room_id,
                            'error': f'Hóa đơn đã được tạo cho chỉ số với detail_id {detail.detail_id} trong tháng {bill_month_date.strftime("%Y-%m")}'
                        })
                        continue

                    bill = MonthlyBill(
                        user_id=user_id,
                        detail_id=detail.detail_id,
                        room_id=room_id,
                        bill_month=bill_month_date,
                        total_amount=float(detail.price),
                        payment_method_allowed='VNPAY'
                    )
                    db.session.add(bill)
                    new_bills.append(bill)
                    logging.debug(f"Created new bill with bill_id {bill.bill_id} for room_id {room_id}")

            db.session.commit()
            logging.info(f"Created {len(new_bills)} new bills")

            # Send notifications for each bill to all users in the room
            for bill in new_bills:
                try:
                    room = Room.query.get(bill.room_id)
                    bill_detail = BillDetail.query.get(bill.detail_id)
                    service_rate = ServiceRate.query.get(bill_detail.rate_id)
                    service = Service.query.get(service_rate.service_id)

                    # Find all users who have ever had a contract for the room (active or inactive)
                    contracts = Contract.query.filter_by(room_id=bill.room_id).all()
                    user_ids = list(set(contract.user_id for contract in contracts if contract.user_id))
                    logging.debug(f"Found {len(user_ids)} users (past or present) for room_id {bill.room_id}: {user_ids}")

                    if not user_ids:
                        logging.warning(f"No users found for room {bill.room_id} for bill {bill.bill_id}")
                        continue

                    # Create a single notification for the bill, targeting the room
                    notification = Notification(
                        title="Hóa đơn mới đã được tạo",
                        message=f"Hóa đơn của dịch vụ {service.name} cho tháng {bill.bill_month.strftime('%Y-%m')} đã được tạo. Tổng tiền: {bill.total_amount} VND. Vui lòng thanh toán sớm nhất có thể.",
                        target_type="ROOM",
                        target_id=bill.room_id,
                        related_entity_type="MONTHLY_BILL",
                        related_entity_id=bill.bill_id,
                        created_at=datetime.utcnow()
                    )
                    db.session.add(notification)
                    db.session.flush()
                    logging.debug(f"Notification created for bill {bill.bill_id}, notification_id={notification.id}")

                    # Create NotificationRecipient records and send FCM notifications for all users
                    for user_id in user_ids:
                        recipient = NotificationRecipient(
                            notification_id=notification.id,
                            user_id=user_id,
                            is_read=False
                        )
                        db.session.add(recipient)
                        try:
                            send_fcm_notification(
                                user_id=user_id,
                                title=notification.title,
                                message=notification.message,
                                data={
                                    'notification_id': str(notification.id),
                                    'related_entity_type': 'MONTHLY_BILL',
                                    'related_entity_id': str(bill.bill_id)
                                }
                            )
                            logging.debug(f"FCM notification sent to user {user_id} for notification_id {notification.id}")
                        except Exception as e:
                            logging.error(f"Failed to send FCM notification to user {user_id}: {str(e)}")

                    db.session.commit()
                    logging.info(f"Notification created for bill {bill.bill_id} and sent to users {user_ids}")
                except Exception as e:
                    db.session.rollback()
                    logging.error(f"Failed to create notification for bill {bill.bill_id} for room {bill.room_id}: {str(e)}")
                    continue  # Continue without failing the request

            results = [bill.to_dict() for bill in new_bills]
            response = {
                'bills_created': results,
                'errors': errors,
                'message': 'Tạo hóa đơn hàng tháng đã hoàn tất' if results else 'Không có hóa đơn nào được tạo do không tìm thấy chỉ số phù hợp hoặc đã tồn tại hóa đơn'
            }
            logging.info(f"Response: {response}")
            return jsonify(response), 201 if results else 400

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in create_monthly_bills_bulk: {str(e)}")
            return jsonify({'message': 'Lỗi khi tạo hóa đơn', 'error': str(e)}), 500

    except Exception as e:
        logging.error(f"Error in create_monthly_bills_bulk: {str(e)}")
        return jsonify({'message': 'Lỗi khi tạo hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/bill-details', methods=['GET'])
@admin_required()
def get_all_bill_details():
    logging.debug("GET /admin/bill-details")
    try:
        bill_details = BillDetail.query.all()
        # Fetch all rooms in one query
        rooms = Room.query.all()
        room_dict = {room.room_id: room.name for room in rooms}
        
        # Serialize bill details and include room_name
        result = []
        for detail in bill_details:
            detail_dict = detail.to_dict()
            detail_dict['room_name'] = room_dict.get(detail.room_id, 'N/A')
            result.append(detail_dict)
            
        logging.debug(f"Returning {len(result)} bill details")
        return jsonify(result), 200

    except Exception as e:
        logging.error(f"Error in get_all_bill_details: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy danh sách chỉ số', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/bill-details/<int:detail_id>', methods=['GET'])
@admin_required()
def get_bill_detail(detail_id):
    logging.debug(f"GET /admin/bill-details/{detail_id}")
    try:
        bill_detail = BillDetail.query.get(detail_id)
        if not bill_detail:
            logging.error(f"Bill detail not found for detail_id {detail_id}")
            return jsonify({'message': f'Không tìm thấy chi tiết hóa đơn với ID {detail_id}'}), 404

        logging.debug(f"Returning bill detail: {bill_detail.to_dict()}")
        return jsonify(bill_detail.to_dict()), 200

    except Exception as e:
        logging.error(f"Error in get_bill_detail: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy chi tiết hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/bill-details/<int:detail_id>', methods=['PUT'])
@admin_required()
def update_bill_detail(detail_id):
    logging.debug(f"PUT /admin/bill-details/{detail_id} with data: {request.get_json()}")
    try:
        bill_detail = BillDetail.query.get(detail_id)
        if not bill_detail:
            logging.error(f"Bill detail not found for detail_id {detail_id}")
            return jsonify({'message': f'Không tìm thấy chi tiết hóa đơn với ID {detail_id}'}), 404

        try:
            data = request.get_json()
        except Exception:
            logging.error("Invalid JSON data")
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

        if 'current_reading' in data:
            try:
                current_reading = float(data['current_reading'])
                if current_reading < 0:
                    return jsonify({'message': 'Chỉ số hiện tại không được âm'}), 400
                if current_reading < bill_detail.previous_reading:
                    return jsonify({'message': 'Chỉ số hiện tại phải lớn hơn hoặc bằng chỉ số trước đó'}), 400
                bill_detail.current_reading = current_reading

                usage = bill_detail.current_reading - bill_detail.previous_reading
                rate = ServiceRate.query.get(bill_detail.rate_id)
                if not rate:
                    logging.error(f"Service rate not found for rate_id {bill_detail.rate_id}")
                    return jsonify({'message': 'Không tìm thấy mức giá liên quan đến chi tiết hóa đơn'}), 404
                bill_detail.price = usage * float(rate.unit_price)

                monthly_bill = MonthlyBill.query.filter_by(detail_id=detail_id).first()
                if monthly_bill:
                    monthly_bill.total_amount = bill_detail.price
            except (TypeError, ValueError):
                logging.error(f"Invalid current_reading: {data['current_reading']}")
                return jsonify({'message': 'Chỉ số hiện tại phải là số hợp lệ'}), 400

        if 'previous_reading' in data:
            try:
                previous_reading = float(data['previous_reading'])
                if previous_reading < 0:
                    return jsonify({'message': 'Chỉ số trước đó không được âm'}), 400
                if bill_detail.current_reading < previous_reading:
                    return jsonify({'message': 'Chỉ số hiện tại phải lớn hơn hoặc bằng chỉ số trước đó'}), 400
                bill_detail.previous_reading = previous_reading

                usage = bill_detail.current_reading - bill_detail.previous_reading
                rate = ServiceRate.query.get(bill_detail.rate_id)
                if not rate:
                    logging.error(f"Service rate not found for rate_id {bill_detail.rate_id}")
                    return jsonify({'message': 'Không tìm thấy mức giá liên quan đến chi tiết hóa đơn'}), 404
                bill_detail.price = usage * float(rate.unit_price)

                monthly_bill = MonthlyBill.query.filter_by(detail_id=detail_id).first()
                if monthly_bill:
                    monthly_bill.total_amount = bill_detail.price
            except (TypeError, ValueError):
                logging.error(f"Invalid previous_reading: {data['previous_reading']}")
                return jsonify({'message': 'Chỉ số trước đó phải là số hợp lệ'}), 400

        if 'price' in data:
            try:
                price = float(data['price'])
                if price < 0:
                    return jsonify({'message': 'Giá không được âm'}), 400
                bill_detail.price = price

                monthly_bill = MonthlyBill.query.filter_by(detail_id=detail_id).first()
                if monthly_bill:
                    monthly_bill.total_amount = price
            except (TypeError, ValueError):
                logging.error(f"Invalid price: {data['price']}")
                return jsonify({'message': 'Giá phải là số hợp lệ'}), 400

        db.session.commit()
        logging.info(f"Updated BillDetail with ID {detail_id}")
        return jsonify(bill_detail.to_dict()), 200

    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError in update_bill_detail: {str(e)}")
        return jsonify({'message': 'Lỗi khi cập nhật: Có bản ghi liên quan không thể cập nhật do ràng buộc khóa ngoại'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in update_bill_detail: {str(e)}")
        return jsonify({'message': 'Lỗi khi cập nhật chi tiết hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/bill-details/<int:detail_id>', methods=['DELETE'])
@admin_required()
def delete_bill_detail(detail_id):
    logging.debug(f"DELETE /admin/bill-details/{detail_id}")
    try:
        bill_detail = BillDetail.query.get(detail_id)
        if not bill_detail:
            logging.error(f"Bill detail not found for detail_id {detail_id}")
            return jsonify({'message': f'Không tìm thấy chi tiết hóa đơn với ID {detail_id}'}), 404

        monthly_bill = MonthlyBill.query.filter_by(detail_id=detail_id).first()
        if monthly_bill:
            logging.error(f"Cannot delete bill detail {detail_id} as it is linked to a monthly bill")
            return jsonify({'message': 'Không thể xóa chi tiết hóa đơn vì đã được liên kết với một hóa đơn hàng tháng'}), 409

        db.session.delete(bill_detail)
        db.session.commit()
        logging.info(f"Deleted BillDetail with ID {detail_id}")
        return jsonify({'message': f'Đã xóa chi tiết hóa đơn với ID {detail_id}'}), 200

    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError in delete_bill_detail: {str(e)}")
        return jsonify({'message': 'Lỗi khi xóa: Có bản ghi liên quan không thể xóa do ràng buộc khóa ngoại'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in delete_bill_detail: {str(e)}")
        return jsonify({'message': 'Lỗi khi xóa chi tiết hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/monthly-bills', methods=['GET'])
@admin_required()
def get_all_monthly_bills():
    logging.debug("GET /admin/monthly-bills")
    try:
        monthly_bills = MonthlyBill.query.all()
        logging.debug(f"Returning {len(monthly_bills)} monthly bills")
        return jsonify([bill.to_dict() for bill in monthly_bills]), 200

    except Exception as e:
        logging.error(f"Error in get_all_monthly_bills: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy danh sách hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/monthly-bills/<int:bill_id>', methods=['GET'])
@admin_required()
def get_monthly_bill(bill_id):
    logging.debug(f"GET /admin/monthly-bills/{bill_id}")
    try:
        monthly_bill = MonthlyBill.query.get(bill_id)
        if not monthly_bill:
            logging.error(f"Monthly bill not found for bill_id {bill_id}")
            return jsonify({'message': f'Không tìm thấy hóa đơn với ID {bill_id}'}), 404

        logging.debug(f"Returning monthly bill: {monthly_bill.to_dict()}")
        return jsonify(monthly_bill.to_dict()), 200

    except Exception as e:
        logging.error(f"Error in get_monthly_bill: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/my-bills', methods=['GET'])
@jwt_required()
def get_my_bills():
    logging.debug(f"GET /my-bills with params: {request.args}")
    try:
        identity = get_jwt_identity()
        try:
            if isinstance(identity, dict):
                user_id = identity['id']
                user_type = identity.get('type', 'USER')
            else:
                user_id = int(identity)
                user_type = get_jwt().get('type', 'USER')
        except (TypeError, ValueError) as e:
            logging.error(f"Invalid identity format: {str(e)}")
            return jsonify({'message': 'Token không hợp lệ', 'error': str(e)}), 401

        if user_type not in ['USER', 'ADMIN']:
            return jsonify({'message': 'Yêu cầu quyền người dùng hoặc admin'}), 403

        # Get room_id from active contract
        room_id = get_active_room_id(user_id)
        if not room_id:
            return jsonify({'message': 'Bạn không có hợp đồng hoạt động nào'}), 403

        room = Room.query.get(room_id)
        if not room:
            logging.error(f"Room not found for room_id {room_id}")
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        if user_type != 'ADMIN':
            user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
            if not user:
                logging.error(f"User not found for user_id {user_id}")
                return jsonify({'message': 'Không tìm thấy người dùng hoặc người dùng đã bị xóa'}), 404

            if not any(contract.room_id == room_id and contract.status == 'ACTIVE' for contract in user.contracts):
                logging.error(f"User {user_id} not authorized for room_id {room_id}")
                return jsonify({'message': 'Bạn không có quyền xem hóa đơn của phòng này'}), 403

        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        bill_month = request.args.get('bill_month', type=str)
        payment_status = request.args.get('payment_status', type=str)

        if page <= 0 or limit <= 0:
            return jsonify({'message': 'Page và limit phải lớn hơn 0'}), 400

        query = MonthlyBill.query.filter_by(room_id=room_id)
        if bill_month:
            try:
                bill_month_date = datetime.strptime(bill_month + '-01', '%Y-%m-%d').date()
                query = query.filter_by(bill_month=bill_month_date)
            except ValueError:
                logging.error(f"Invalid bill_month format: {bill_month}")
                return jsonify({'message': 'Định dạng bill_month không hợp lệ (YYYY-MM)'}), 400

        if payment_status:
            allowed_statuses = ['PENDING', 'PAID', 'FAILED', 'OVERDUE', 'NOT_PAID']
            if payment_status.upper() not in allowed_statuses:
                logging.error(f"Invalid payment_status: {payment_status}")
                return jsonify({'message': f'Trạng thái thanh toán không hợp lệ. Phải là một trong: {allowed_statuses}'}), 400
            if payment_status.upper() == 'NOT_PAID':
                query = query.filter(MonthlyBill.payment_status != 'PAID')
            else:
                query = query.filter_by(payment_status=payment_status.upper())

        query = query.order_by(MonthlyBill.created_at.desc())

        sql_query = str(query)
        logging.debug(f"SQL Query: {sql_query}")

        total_bills = query.count()
        logging.debug(f"Total bills before pagination: {total_bills}")

        all_bills = query.all()
        logging.debug(f"All bills before pagination: {[bill.to_dict() for bill in all_bills]}")

        offset = (page - 1) * limit
        bills = query.offset(offset).limit(limit).all()
        total_pages = (total_bills + limit - 1) // limit if total_bills > 0 else 1

        logging.debug(f"Bills after pagination: {len(bills)}")
        logging.debug(f"Bills after pagination (details): {[bill.to_dict() for bill in bills]}")

        if not bills:
            logging.debug("No bills found after pagination")
            return jsonify({
                'message': 'Không tìm thấy hóa đơn nào',
                'bills': [],
                'total': 0,
                'pages': 0,
                'current_page': page
            }), 404

        return jsonify({
            'bills': [bill.to_dict() for bill in bills],
            'total': total_bills,
            'pages': total_pages,
            'current_page': page
        }), 200

    except Exception as e:
        logging.error(f"Error in get_my_bills: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy danh sách hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/monthly-bills/<int:bill_id>', methods=['PUT'])
@admin_required()
def update_monthly_bill(bill_id):
    logging.debug(f"PUT /admin/monthly-bills/{bill_id} with data: {request.get_json()}")
    try:
        monthly_bill = MonthlyBill.query.get(bill_id)
        if not monthly_bill:
            logging.error(f"Monthly bill not found for bill_id {bill_id}")
            return jsonify({'message': f'Không tìm thấy hóa đơn với ID {bill_id}'}), 404

        try:
            data = request.get_json()
        except Exception:
            logging.error("Invalid JSON data")
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

        if 'total_amount' in data:
            try:
                total_amount = float(data['total_amount'])
                if total_amount < 0:
                    return jsonify({'message': 'Tổng tiền không được âm'}), 400
                monthly_bill.total_amount = total_amount
            except (TypeError, ValueError):
                logging.error(f"Invalid total_amount: {data['total_amount']}")
                return jsonify({'message': 'Tổng tiền phải là số hợp lệ'}), 400

        if 'payment_status' in data:
            allowed_statuses = ['PENDING', 'PAID', 'FAILED', 'OVERDUE']
            payment_status = data['payment_status']
            if payment_status not in allowed_statuses:
                logging.error(f"Invalid payment_status: {payment_status}")
                return jsonify({'message': f'Trạng thái thanh toán không hợp lệ. Phải là một trong: {allowed_statuses}'}), 400
            monthly_bill.payment_status = payment_status

            if payment_status == 'PAID':
                monthly_bill.paid_at = datetime.now()

        if 'payment_method_allowed' in data:
            monthly_bill.payment_method_allowed = data['payment_method_allowed']

        if 'transaction_reference' in data:
            monthly_bill.transaction_reference = data['transaction_reference']

        db.session.commit()
        logging.info(f"Updated MonthlyBill with ID {bill_id}")
        return jsonify(monthly_bill.to_dict()), 200

    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError in update_monthly_bill: {str(e)}")
        return jsonify({'message': 'Lỗi khi cập nhật: Có bản ghi liên quan không thể cập nhật do ràng buộc khóa ngoại'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in update_monthly_bill: {str(e)}")
        return jsonify({'message': 'Lỗi khi cập nhật hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/monthly-bills/<int:bill_id>', methods=['DELETE'])
@admin_required()
def delete_monthly_bill(bill_id):
    logging.debug(f"DELETE /admin/monthly-bills/{bill_id}")
    try:
        monthly_bill = MonthlyBill.query.get(bill_id)
        if not monthly_bill:
            logging.error(f"Monthly bill not found for bill_id {bill_id}")
            return jsonify({'message': f'Không tìm thấy hóa đơn với ID {bill_id}'}), 404

        if monthly_bill.payment_status == 'PAID':
            logging.error(f"Cannot delete paid bill {bill_id}")
            return jsonify({'message': 'Không thể xóa hóa đơn đã thanh toán'}), 409

        db.session.delete(monthly_bill)
        db.session.commit()
        logging.info(f"Deleted MonthlyBill with ID {bill_id}")
        return jsonify({'message': f'Đã xóa hóa đơn với ID {bill_id}'}), 200

    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError in delete_monthly_bill: {str(e)}")
        return jsonify({'message': 'Lỗi khi xóa: Có bản ghi liên quan không thể xóa do ràng buộc khóa ngoại'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in delete_monthly_bill: {str(e)}")
        return jsonify({'message': 'Lỗi khi xóa hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/my-bill-details', methods=['GET'])
@jwt_required()
def get_my_bill_details():
    logging.debug(f"GET /my-bill-details")
    try:
        identity = get_jwt_identity()
        try:
            if isinstance(identity, dict):
                user_id = identity['id']
                user_type = identity.get('type', 'USER')
            else:
                user_id = int(identity)
                user_type = get_jwt().get('type', 'USER')
        except (TypeError, ValueError) as e:
            logging.error(f"Invalid identity format: {str(e)}")
            return jsonify({'message': 'Token không hợp lệ', 'error': str(e)}), 401

        if user_type not in ['USER', 'ADMIN']:
            return jsonify({'message': 'Yêu cầu quyền người dùng hoặc admin'}), 403

        # Get room_id from active contract
        room_id = get_active_room_id(user_id)
        if not room_id:
            return jsonify({'message': 'Bạn không có hợp đồng hoạt động nào'}), 403

        room = Room.query.get(room_id)
        if not room:
            logging.error(f"Room not found for room_id {room_id}")
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        if user_type != 'ADMIN':
            user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
            if not user:
                logging.error(f"User not found for user_id {user_id}")
                return jsonify({'message': 'Không tìm thấy người dùng hoặc người dùng đã bị xóa'}), 404

            if not any(contract.room_id == room_id and contract.status == 'ACTIVE' for contract in user.contracts):
                logging.error(f"User {user_id} not authorized for room_id {room_id}")
                return jsonify({'message': 'Bạn không có quyền xem chỉ số của phòng này'}), 403

        bill_details = BillDetail.query.filter_by(
            room_id=room_id
        ).all()

        logging.debug(f"Returning {len(bill_details)} bill details for room_id {room_id}")
        return jsonify([detail.to_dict() for detail in bill_details]), 200

    except Exception as e:
        logging.error(f"Error in get_my_bill_details: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy danh sách chỉ số', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/paid-bills', methods=['DELETE'])
@admin_required()
def delete_paid_bills():
    logging.debug("DELETE /admin/paid-bills")
    try:
        try:
            data = request.get_json() or {}
        except Exception:
            logging.error("Invalid JSON data")
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

        bill_ids = data.get('bill_ids')

        if not bill_ids or not isinstance(bill_ids, list):
            logging.error("Invalid or missing bill_ids")
            return jsonify({'message': 'Yêu cầu danh sách bill_ids hợp lệ'}), 400

        paid_bills = MonthlyBill.query.filter(
            MonthlyBill.bill_id.in_(bill_ids),
            MonthlyBill.payment_status == 'PAID'
        ).all()

        if not paid_bills:
            logging.debug("No paid bills found for provided bill_ids")
            return jsonify({'message': 'Không tìm thấy hóa đơn nào đã thanh toán trong danh sách cung cấp'}), 404

        provided_ids = set(bill_ids)
        found_ids = set(bill.bill_id for bill in paid_bills)
        missing_ids = provided_ids - found_ids
        if missing_ids:
            logging.debug(f"Bills not found for IDs: {missing_ids}")
            return jsonify({'message': f'Không tìm thấy hóa đơn với ID: {missing_ids}'}), 404

        deleted_bill_ids = []
        deleted_detail_ids = []

        try:
            for bill in paid_bills:
                detail_id = bill.detail_id

                deleted_bill_ids.append(bill.bill_id)
                db.session.delete(bill)

                bill_detail = BillDetail.query.get(detail_id)
                if bill_detail:
                    deleted_detail_ids.append(detail_id)
                    db.session.delete(bill_detail)
                else:
                    logging.warning(f"BillDetail with ID {detail_id} not found for MonthlyBill {bill.bill_id}")

            db.session.commit()
            logging.info(f"Deleted MonthlyBills: {deleted_bill_ids}, BillDetails: {deleted_detail_ids}")
            return jsonify({
                'message': 'Đã xóa các hóa đơn và chi tiết hóa đơn đã thanh toán',
                'deleted_monthly_bills': deleted_bill_ids,
                'deleted_bill_details': deleted_detail_ids
            }), 200

        except IntegrityError as e:
            db.session.rollback()
            logging.error(f"IntegrityError in delete_paid_bills: {str(e)}")
            return jsonify({'message': 'Lỗi khi xóa: Có bản ghi liên quan không thể xóa do ràng buộc khóa ngoại'}), 409
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in delete_paid_bills: {str(e)}")
            return jsonify({'message': 'Lỗi khi xóa hóa đơn', 'error': str(e)}), 500

    except Exception as e:
        logging.error(f"Error in delete_paid_bills: {str(e)}")
        return jsonify({'message': 'Lỗi khi xóa hóa đơn', 'error': str(e)}), 500