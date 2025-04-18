from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from models.monthly_bill import MonthlyBill
from models.bill_detail import BillDetail
from models.user import User
from models.room import Room
from models.service import Service
from models.service_rate import ServiceRate
from controllers.auth_controller import admin_required, user_required
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import logging

logging.basicConfig(level=logging.INFO)

monthly_bill_bp = Blueprint('monthly_bill', __name__)

@monthly_bill_bp.route('/rooms/<int:room_id>/bill-details', methods=['POST'])
@user_required()
def submit_bill_detail(room_id):
    logging.info(f"POST /rooms/{room_id}/bill-details with data: {request.get_json()}")
    try:
        identity = get_jwt_identity()
        # Xử lý identity có thể là chuỗi hoặc dictionary
        try:
            user_id = identity['id'] if isinstance(identity, dict) else int(identity)
        except (TypeError, ValueError) as e:
            logging.error(f"Invalid identity format: {str(e)}")
            return jsonify({'message': 'Token không hợp lệ', 'error': str(e)}), 401

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
            return jsonify({'message': 'Yêu cầu bill_month và readings'}), 400

        try:
            bill_month_date = datetime.strptime(bill_month, '%Y-%m-%d').date()
            if bill_month_date.day != 1:
                return jsonify({'message': 'bill_month phải là ngày đầu tháng (YYYY-MM)'}), 400
        except ValueError:
            return jsonify({'message': 'Định dạng bill_month không hợp lệ (YYYY-MM)'}), 400

        services = Service.query.all()
        if not services:
            return jsonify({'message': 'Không tìm thấy dịch vụ nào'}), 404

        valid_service_ids = {str(service.service_id) for service in services}

        # Kiểm tra trùng lặp cho từng dịch vụ
        for service_id in readings:
            if service_id not in valid_service_ids:
                return jsonify({'message': f'ID dịch vụ {service_id} không hợp lệ'}), 400

            # Tìm rate_id cho service_id
            rate = ServiceRate.query.filter(
                ServiceRate.service_id == int(service_id),
                ServiceRate.effective_date <= bill_month_date
            ).order_by(ServiceRate.effective_date.desc()).first()

            if not rate:
                return jsonify({'message': f'Không tìm thấy mức giá hiện tại cho dịch vụ ID {service_id}'}), 404

            # Kiểm tra xem đã có ai submit chỉ số cho phòng, tháng, và dịch vụ này chưa
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

            for service in services:
                service_id = str(service.service_id)
                if service_id not in readings:
                    return jsonify({'message': f'Yêu cầu chỉ số cho dịch vụ ID {service_id} ({service.name})'}), 400

                if not isinstance(readings[service_id], dict):
                    return jsonify({'message': f'Chỉ số cho dịch vụ ID {service_id} ({service.name}) phải là một object'}), 400

                current = readings[service_id].get('current')
                if current is None:
                    return jsonify({'message': f'Yêu cầu current cho dịch vụ ID {service_id} ({service.name})'}), 400

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
                    return jsonify({'message': f'Chỉ số hiện tại phải lớn hơn hoặc bằng chỉ số trước đó cho dịch vụ ID {service_id} ({service.name})'}), 400

                with db.session.no_autoflush:
                    rate = ServiceRate.query.filter(
                        ServiceRate.service_id == service.service_id,
                        ServiceRate.effective_date <= bill_month_date
                    ).order_by(ServiceRate.effective_date.desc()).first()

                if not rate:
                    return jsonify({'message': f'Không tìm thấy mức giá hiện tại cho dịch vụ ID {service_id} ({service.name})'}), 404

                usage = current - previous
                price = usage * float(rate.unit_price)

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
            return jsonify([detail.to_dict() for detail in bill_details]), 201

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in submit_bill_detail: {str(e)}")
            return jsonify({'message': 'Lỗi khi gửi chỉ số', 'error': str(e)}), 500

    except Exception as e:
        logging.error(f"Error in submit_bill_detail: {str(e)}")
        return jsonify({'message': 'Lỗi khi gửi chỉ số', 'error': str(e)}), 500


# Tạo nhiều hóa đơn cùng lúc (Admin)
@monthly_bill_bp.route('/admin/monthly-bills/bulk', methods=['POST'])
@admin_required()
def create_monthly_bills_bulk():
    logging.info(f"POST /admin/monthly-bills/bulk with data: {request.get_json()}")
    try:
        try:
            data = request.get_json()
        except Exception:
            logging.error("Invalid JSON data")
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

        bill_month = data.get('bill_month')
        room_ids = data.get('room_ids')

        if not bill_month:
            return jsonify({'message': 'Yêu cầu bill_month'}), 400

        try:
            bill_month_date = datetime.strptime(bill_month, '%Y-%m-%d').date()
            if bill_month_date.day != 1:
                return jsonify({'message': 'bill_month phải là ngày đầu tháng (YYYY-MM-01)'}), 400
        except ValueError:
            return jsonify({'message': 'Định dạng bill_month không hợp lệ (YYYY-MM-DD)'}), 400

        if room_ids:
            rooms = Room.query.filter(Room.room_id.in_(room_ids)).all()
            if len(rooms) != len(room_ids):
                invalid_ids = set(room_ids) - set(room.room_id for room in rooms)
                return jsonify({'message': f'Không tìm thấy phòng với ID: {invalid_ids}'}), 404
        else:
            rooms = Room.query.all()

        if not rooms:
            return jsonify({'message': 'Không tìm thấy phòng nào'}), 404

        new_bills = []
        errors = []

        try:
            for room in rooms:
                room_id = room.room_id

                # Lấy BillDetail chưa được liên kết với MonthlyBill
                bill_details = BillDetail.query.filter(
                    BillDetail.room_id == room_id,
                    BillDetail.bill_month == bill_month_date,
                    ~BillDetail.detail_id.in_(
                        db.session.query(MonthlyBill.detail_id).filter(MonthlyBill.bill_month == bill_month_date)
                    )
                ).all()

                if not bill_details:
                    errors.append({'room_id': room_id, 'error': 'Không tìm thấy chỉ số dịch vụ chưa liên kết cho tháng này'})
                    continue

                contract = next(
                    (c for c in room.contracts if c.status == 'ACTIVE' and c.user_id),
                    None
                )
                if not contract:
                    errors.append({'room_id': room_id, 'error': 'Không tìm thấy hợp đồng hoạt động cho phòng'})
                    continue

                user_id = contract.user_id
                user = User.query.get(user_id)
                if not user:
                    errors.append({'room_id': room_id, 'error': f'Không tìm thấy người dùng với ID {user_id}'})
                    continue

                for detail in bill_details:
                    # Kiểm tra trùng lặp dựa trên room_id, bill_month, detail_id
                    existing_bill = MonthlyBill.query.filter_by(
                        room_id=room_id,
                        bill_month=bill_month_date,
                        detail_id=detail.detail_id
                    ).first()
                    if existing_bill:
                        errors.append({'room_id': room_id, 'error': f'Hóa đơn đã tồn tại cho detail_id {detail.detail_id}'})
                        continue

                    bill = MonthlyBill(
                        user_id=user_id,
                        detail_id=detail.detail_id,
                        room_id=room_id,
                        bill_month=bill_month_date,
                        total_amount=float(detail.price),
                        payment_method_allowed='VIETQR,CASH,BANK_TRANSFER'
                    )
                    db.session.add(bill)
                    new_bills.append(bill)

            db.session.commit()

            # Sau khi commit, gọi to_dict() để đảm bảo dữ liệu được tải
            results = [bill.to_dict() for bill in new_bills]
            response = {'bills_created': results, 'errors': errors}
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
    logging.info("GET /admin/bill-details")
    try:
        bill_details = BillDetail.query.all()
        return jsonify([detail.to_dict() for detail in bill_details]), 200

    except Exception as e:
        logging.error(f"Error in get_all_bill_details: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy danh sách chỉ số', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/monthly-bills', methods=['GET'])
@admin_required()
def get_all_monthly_bills():
    logging.info("GET /admin/monthly-bills")
    try:
        monthly_bills = MonthlyBill.query.all()
        return jsonify([bill.to_dict() for bill in monthly_bills]), 200

    except Exception as e:
        logging.error(f"Error in get_all_monthly_bills: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy danh sách hóa đơn', 'error': str(e)}), 500

@monthly_bill_bp.route('/rooms/<int:room_id>/my-bill-details', methods=['GET'])
@jwt_required()
def get_my_bill_details(room_id):
    logging.info(f"GET /rooms/{room_id}/my-bill-details")
    try:
        identity = get_jwt_identity()
        try:
            if isinstance(identity, dict):
                user_id = identity['id']
                user_type = identity.get('type', 'USER')
            else:
                user_id = int(identity)
                user_type = get_jwt().get('type', 'USER')  # Lấy type từ token nếu identity là chuỗi
        except (TypeError, ValueError) as e:
            logging.error(f"Invalid identity format: {str(e)}")
            return jsonify({'message': 'Token không hợp lệ', 'error': str(e)}), 401

        if user_type not in ['USER', 'ADMIN']:
            return jsonify({'message': 'Yêu cầu quyền người dùng hoặc admin'}), 403

        room = Room.query.get(room_id)
        if not room:
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        # Kiểm tra quyền truy cập cho user
        if user_type != 'ADMIN':
            user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
            if not user:
                return jsonify({'message': 'Không tìm thấy người dùng hoặc người dùng đã bị xóa'}), 404

            if not any(contract.room_id == room_id and contract.status == 'ACTIVE' for contract in user.contracts):
                return jsonify({'message': 'Bạn không có quyền xem chỉ số của phòng này'}), 403

        # Lấy tất cả BillDetail của phòng
        bill_details = BillDetail.query.filter_by(
            room_id=room_id
        ).all()

        return jsonify([detail.to_dict() for detail in bill_details]), 200

    except Exception as e:
        logging.error(f"Error in get_my_bill_details: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy danh sách chỉ số', 'error': str(e)}), 500

@monthly_bill_bp.route('/admin/paid-bills', methods=['DELETE'])
@admin_required()
def delete_paid_bills():
    logging.info("DELETE /admin/paid-bills")
    try:
        # Tính ngày giới hạn (6 tháng trước)
        cutoff_date = datetime.now() - timedelta(days=180)

        # Tìm tất cả MonthlyBill đã thanh toán và cũ hơn 6 tháng
        paid_bills = MonthlyBill.query.filter(
            MonthlyBill.payment_status == 'PAID',
            MonthlyBill.paid_at < cutoff_date
        ).all()

        if not paid_bills:
            return jsonify({'message': 'Không tìm thấy hóa đơn nào đã thanh toán để xóa (cũ hơn 6 tháng)'}), 404

        deleted_bill_ids = []
        deleted_detail_ids = []

        try:
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
                else:
                    logging.warning(f"BillDetail with ID {detail_id} not found for MonthlyBill {bill.bill_id}")

            db.session.commit()
            logging.info(f"Deleted MonthlyBills: {deleted_bill_ids}, BillDetails: {deleted_detail_ids}")
            return jsonify({
                'message': 'Đã xóa các hóa đơn và chi tiết hóa đơn đã thanh toán (cũ hơn 6 tháng)',
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