from flask import Blueprint, request, jsonify,current_app
from flask_jwt_extended import jwt_required
from extensions  import db, mail
from models.register import Register
from models.room import Room
from models.contract import Contract
from controllers.auth_controller import admin_required
from datetime import datetime, timedelta
from flask_mail import Message
from dateutil.parser import parse
import logging
import re
from flask import render_template
registration_bp = Blueprint('registration', __name__)
logger = logging.getLogger(__name__)
# Tạo yêu cầu đăng ký phòng (public, không cần xác thực)
@registration_bp.route('/registrations', methods=['POST'])
def create_registration():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        name_student = data.get('name_student')
        email = data.get('email')
        phone_number = data.get('phone_number')
        room_id = data.get('room_id')
        information = data.get('information')
        number_of_people = data.get('number_of_people', 1)

        if not all([name_student, email, phone_number, room_id, number_of_people]):
            return jsonify({'message': 'Yêu cầu name_student, email, phone_number, room_id và number_of_people'}), 400

        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            return jsonify({'message': 'Định dạng email không hợp lệ'}), 400

        room = Room.query.get(room_id)
        if not room:
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        current_date = datetime.now().date()
        active_contracts = Contract.query.filter(
            Contract.room_id == room_id,
            Contract.status == 'ACTIVE',
            Contract.start_date <= current_date,
            Contract.end_date >= current_date
        ).count()

        available_slots = room.capacity - active_contracts
        if number_of_people > available_slots:
            return jsonify({'message': 'Phòng không đủ chỗ cho số người đăng ký'}), 400

        existing_registration = Register.query.filter_by(email=email).filter(
            Register.status.in_(['PENDING', 'APPROVED'])
        ).first()
        if existing_registration:
            return jsonify({'message': 'Email này đã được sử dụng để đăng ký, vui lòng chờ xử lý'}), 400

        registration = Register(
            name_student=name_student,
            email=email,
            phone_number=phone_number,
            room_id=room_id,
            information=information,
            status='PENDING',
            number_of_people=number_of_people
        )
        db.session.add(registration)
        db.session.commit()

        try:
            sender = current_app.config.get('MAIL_DEFAULT_SENDER')
            if not sender:
                raise ValueError("MAIL_DEFAULT_SENDER chưa được cấu hình")

            msg = Message(
                subject='Xác nhận đăng ký phòng ký túc xá',
                sender=sender,
                recipients=[email]
            )
            msg.html = render_template(
                'emails/registration_confirmation.html',
                name_student=name_student,
                email=email,
                phone_number=phone_number,
                room_name=room.name,
                number_of_people=number_of_people
            )
            mail.send(msg)
            logger.info("Gửi email xác nhận đăng ký thành công tới %s", email)
        except Exception as e:
            logger.error("Gửi email xác nhận thất bại tới %s: %s", email, str(e))
            return jsonify({
                'message': 'Đăng ký thành công nhưng không thể gửi email xác nhận. Vui lòng liên hệ quản trị viên.',
                'registration': registration.to_dict()
            }), 201

        logger.info("Tạo đăng ký thành công cho email %s", email)
        return jsonify({
            'message': 'Đăng ký thành công! Email xác nhận đã được gửi.',
            'registration': registration.to_dict()
        }), 201

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /registrations POST với email %s: %s", email or "không xác định", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        logger.error("Lỗi server trong /registrations POST với email %s: %s", email or "không xác định", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Lấy danh sách tất cả yêu cầu đăng ký (Admin)
@registration_bp.route('/registrations', methods=['GET'])
@admin_required()
def get_all_registrations():
    # Lấy các tham số từ query
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    status = request.args.get('status', type=str)
    room_id = request.args.get('room_id', type=int)
    name_student = request.args.get('name_student', type=str)
    meeting_datetime = request.args.get('meeting_datetime', type=str)

    # Bắt đầu với query cơ bản
    query = Register.query

    # Áp dụng các bộ lọc nếu có
    if status:
        query = query.filter_by(status=status.upper())
    if room_id:
        query = query.filter_by(room_id=room_id)
    if name_student:
        query = query.filter(Register.name_student.ilike(f"%{name_student}%"))
    if meeting_datetime:
        try:
            meeting_date = datetime.strptime(meeting_datetime, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Register.meeting_datetime) == meeting_date)
        except ValueError:
            return jsonify({'message': 'Định dạng ngày không hợp lệ, sử dụng YYYY-MM-DD'}), 400

    # Phân trang và lấy kết quả
    registrations = query.paginate(page=page, per_page=limit)

    # Trả về kết quả dạng JSON
    return jsonify({
        'registrations': [registration.to_dict() for registration in registrations.items],
        'total': registrations.total,
        'pages': registrations.pages,
        'current_page': registrations.page
    }), 200

# Lấy chi tiết yêu cầu đăng ký theo ID (Admin)
@registration_bp.route('/registrations/<int:registration_id>', methods=['GET'])
@admin_required()
def get_registration_by_id(registration_id):
    registration = Register.query.get(registration_id)
    if not registration:
        return jsonify({'message': 'Không tìm thấy yêu cầu đăng ký'}), 404
    data = registration.to_dict()
    print(f"Response data: {data}")
    return jsonify(registration.to_dict()), 200

# Phê duyệt hoặc từ chối yêu cầu đăng ký (Admin)
@registration_bp.route('/registrations/<int:registration_id>/status', methods=['PUT'])
@admin_required()
def update_registration_status(registration_id):
    registration = Register.query.get(registration_id)
    if not registration:
        return jsonify({'message': 'Không tìm thấy yêu cầu đăng ký'}), 404

    if registration.status == 'REJECTED':
        return jsonify({'message': 'Không thể cập nhật trạng thái của yêu cầu đã bị từ chối'}), 400

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

    new_status = data.get('status')
    rejection_reason = data.get('rejection_reason')

    if new_status not in ['APPROVED', 'REJECTED']:
        return jsonify({'message': 'Trạng thái không hợp lệ, phải là APPROVED hoặc REJECTED'}), 400

    if new_status == 'REJECTED' and not rejection_reason:
        return jsonify({'message': 'Yêu cầu lý do từ chối khi trạng thái là REJECTED'}), 400

    registration.status = new_status
    registration.rejection_reason = rejection_reason if new_status == 'REJECTED' else None
    registration.processed_at = datetime.utcnow()
    db.session.commit()

    try:
        sender = current_app.config.get('MAIL_DEFAULT_SENDER')
        if not sender:
            raise ValueError("MAIL_DEFAULT_SENDER chưa được cấu hình")

        msg = Message(
            sender=sender,
            recipients=[registration.email]
        )
        if new_status == 'APPROVED':
            msg.subject = 'Thông báo phê duyệt đăng ký phòng ký túc xá'
            msg.html = render_template(
                'emails/registration_approved.html',
                name_student=registration.name_student,
                number_of_people=registration.number_of_people
            )

        else:  # REJECTED
            msg.subject = 'Thông báo từ chối đăng ký phòng ký túc xá'
            msg.html = render_template(
                'emails/registration_rejected.html',
                name_student=registration.name_student,
                number_of_people=registration.number_of_people,
                rejection_reason=rejection_reason
            )
            msg.body = render_template(
                'emails/registration_rejected.txt',
                name_student=registration.name_student,
                number_of_people=registration.number_of_people,
                rejection_reason=rejection_reason
            )

        mail.send(msg)
        logger.info("Gửi email thông báo trạng thái %s tới %s", new_status, registration.email)
    except Exception as e:
        logger.error("Gửi email thất bại tới %s: %s", registration.email, str(e))
        return jsonify({
            'message': 'Cập nhật trạng thái thành công nhưng không thể gửi email thông báo. Vui lòng liên hệ quản trị viên.',
            'registration': registration.to_dict()
        }), 200

    return jsonify({
        'message': 'Cập nhật trạng thái thành công và email thông báo đã được gửi.',
        'registration': registration.to_dict()
    }), 200

# Thiết lập ngày giờ gặp mặt và gửi email thông báo (Admin)
@registration_bp.route('/registrations/<int:registration_id>/meeting', methods=['PUT'])
@admin_required()
def set_meeting_datetime(registration_id):
    registration = Register.query.get(registration_id)
    if not registration:
        return jsonify({'message': 'Không tìm thấy yêu cầu đăng ký'}), 404

    if registration.status != 'APPROVED':
        return jsonify({'message': 'Yêu cầu phải được phê duyệt (APPROVED) trước khi thiết lập thời gian gặp mặt'}), 400

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

    meeting_datetime_str = data.get('meeting_datetime')
    meeting_location = data.get('meeting_location', "Văn phòng ký túc xá")

    if not meeting_datetime_str:
        return jsonify({'message': 'Yêu cầu meeting_datetime'}), 400

    try:
        meeting_datetime = parse(meeting_datetime_str)
        if meeting_datetime < datetime.utcnow():
            return jsonify({'message': 'Thời gian gặp mặt phải ở tương lai'}), 400
    except ValueError:
        return jsonify({'message': 'Định dạng thời gian không hợp lệ, sử dụng định dạng ISO (VD: 2025-04-15T10:00:00)'}), 400

    registration.meeting_datetime = meeting_datetime
    registration.meeting_location = meeting_location
    room = Room.query.get(registration.room_id)
    db.session.commit()

    try:
        msg = Message(
            subject='Thông báo thời gian gặp mặt để hoàn tất đăng ký phòng',
            sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
            recipients=[registration.email]
        )
        msg.html = render_template(
            'emails/meeting_notification.html',
            name_student=registration.name_student,
            room_name=room.name,
            number_of_people=registration.number_of_people,
            meeting_datetime=meeting_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            meeting_location=meeting_location,
            phone_number=registration.phone_number
        )
        mail.send(msg)
        return jsonify({
            'message': 'Thiết lập thời gian và địa điểm gặp mặt thành công, email thông báo đã được gửi',
            'registration': registration.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Không thể gửi email, vui lòng thử lại sau', 'error': str(e)}), 500

@registration_bp.route('/registrations/batch', methods=['DELETE'])
@admin_required()
def delete_registrations_batch():
    try:
        # Lấy dữ liệu từ request body
        data = request.get_json(silent=True)
        if not data or 'registration_ids' not in data:
            return jsonify({'message': 'Yêu cầu danh sách registration_ids trong body'}), 400

        registration_ids = data['registration_ids']
        if not isinstance(registration_ids, list) or not registration_ids:
            return jsonify({'message': 'Danh sách registration_ids không hợp lệ hoặc trống'}), 400

        # Kiểm tra từng registration_id
        valid_ids = []
        errors = []
        current_time = datetime.now()  # Lấy thời gian hiện tại

        for reg_id in registration_ids:
            registration = Register.query.get(reg_id)
            if not registration:
                errors.append({'registration_id': reg_id, 'error': 'Không tìm thấy đăng ký'})
                continue

            # Nếu trạng thái là PENDING, không cho phép xóa
            if registration.status == 'PENDING':
                errors.append({'registration_id': reg_id, 'error': 'Không thể xóa đăng ký ở trạng thái PENDING'})
                continue

            # Nếu trạng thái là APPROVED, kiểm tra meeting_datetime
            if registration.status == 'APPROVED':
                if registration.meeting_datetime and registration.meeting_datetime > current_time:
                    errors.append({'registration_id': reg_id, 'error': 'Không thể xóa đăng ký APPROVED vì meeting_datetime chưa qua'})
                    continue

            valid_ids.append(reg_id)

        # Nếu không có ID nào hợp lệ để xóa
        if not valid_ids:
            return jsonify({'message': 'Không có đăng ký nào trong danh sách thỏa mãn điều kiện để xóa', 'errors': errors}), 200

        # Xóa các đăng ký hợp lệ
        deleted_ids = []
        for reg_id in valid_ids:
            registration = Register.query.get(reg_id)
            db.session.delete(registration)
            deleted_ids.append(reg_id)

        db.session.commit()

        # Trả về kết quả
        response = {
            'message': f'Đã xóa thành công {len(deleted_ids)} đăng ký',
            'deleted_ids': deleted_ids,
            'errors': errors if errors else []
        }
        return jsonify(response), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500