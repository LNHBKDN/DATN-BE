from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, mail
from models.admin import Admin
from controllers.auth_controller import admin_required
from flask_mail import Message
import re
from datetime import datetime, timedelta
import secrets
import logging

# Thiết lập logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__)

# Hàm kiểm tra độ mạnh của mật khẩu
def is_strong_password(password):
    if not isinstance(password, str):
        return False, "Mật khẩu phải là chuỗi ký tự"
    if len(password) < 8:
        return False, "Mật khẩu phải có ít nhất 8 ký tự"
    if not re.search(r"[A-Z]", password):
        return False, "Mật khẩu phải chứa ít nhất một chữ cái in hoa"
    if not re.search(r"[a-z]", password):
        return False, "Mật khẩu phải chứa ít nhất một chữ cái thường"
    if not re.search(r"[0-9]", password):
        return False, "Mật khẩu phải chứa ít nhất một số"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Mật khẩu phải chứa ít nhất một ký tự đặc biệt"
    return True, ""

# Lấy danh sách tất cả admin
@admin_bp.route('/admin/admins', methods=['GET'])
@admin_required()
def get_all_admins():
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        
        if page < 1 or limit < 1:
            return jsonify({'message': 'Trang hoặc giới hạn không hợp lệ'}), 400

        admins = Admin.query.paginate(page=page, per_page=limit, error_out=False)
        if not admins.items and page > 1:
            return jsonify({'message': 'Trang không tồn tại'}), 404

        return jsonify({
            'admins': [admin.to_dict() for admin in admins.items],
            'total': admins.total,
            'pages': admins.pages,
            'current_page': admins.page
        }), 200

    except Exception as e:
        logger.error("Lỗi trong /admin/admins GET: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Lấy thông tin admin theo ID
@admin_bp.route('/admin/admins/<int:admin_id>', methods=['GET'])
@admin_required()
def get_admin_by_id(admin_id):
    try:
        if admin_id < 1:
            return jsonify({'message': 'ID quản trị viên không hợp lệ'}), 400

        admin = Admin.query.get(admin_id)
        if not admin:
            return jsonify({'message': 'Không tìm thấy quản trị viên'}), 404

        return jsonify(admin.to_dict()), 200

    except Exception as e:
        logger.error("Lỗi trong /admin/admins/%s GET: %s", admin_id, str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Tạo admin mới
@admin_bp.route('/admin/admins', methods=['POST'])
@admin_required()
def create_admin():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        username = data.get('username')
        password = data.get('password')
        email = data.get('email')
        full_name = data.get('full_name')
        phone = data.get('phone')

        if not username or not password or not email:
            return jsonify({'message': 'Thiếu username, password hoặc email'}), 400

        # Kiểm tra định dạng email
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            return jsonify({'message': 'Định dạng email không hợp lệ'}), 400

        # Kiểm tra trùng lặp
        if Admin.query.filter_by(username=username).first():
            return jsonify({'message': 'Username đã tồn tại'}), 400
        if Admin.query.filter_by(email=email).first():
            return jsonify({'message': 'Email đã tồn tại'}), 400

        # Kiểm tra độ mạnh của mật khẩu
        is_strong, message = is_strong_password(password)
        if not is_strong:
            return jsonify({'message': message}), 400

        admin = Admin(
            username=username,
            email=email,
            full_name=full_name,
            phone=phone
        )
        admin.password_hash = generate_password_hash(password)
        db.session.add(admin)
        db.session.commit()

        logger.info("Tạo admin mới thành công: admin_id %s", admin.admin_id)
        return jsonify(admin.to_dict()), 201

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /admin/admins POST: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /admin/admins POST: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Cập nhật thông tin admin
@admin_bp.route('/admin/admins/<int:admin_id>', methods=['PUT'])
@admin_required()
def update_admin(admin_id):
    try:
        if admin_id < 1:
            return jsonify({'message': 'ID quản trị viên không hợp lệ'}), 400

        admin = Admin.query.get(admin_id)
        if not admin:
            return jsonify({'message': 'Không tìm thấy quản trị viên'}), 404

        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        full_name = data.get('full_name')
        email = data.get('email')
        phone = data.get('phone')

        # Kiểm tra định dạng email nếu được cung cấp
        if email:
            email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
            if not re.match(email_regex, email):
                return jsonify({'message': 'Định dạng email không hợp lệ'}), 400
            if email != admin.email:
                existing_admin = Admin.query.filter_by(email=email).first()
                if existing_admin and existing_admin.admin_id != admin_id:
                    return jsonify({'message': 'Email đã tồn tại'}), 400
            admin.email = email

        # Cập nhật các trường khác
        admin.full_name = full_name if full_name is not None else admin.full_name
        admin.phone = phone if phone is not None else admin.phone

        db.session.commit()
        logger.info("Cập nhật admin thành công: admin_id %s", admin_id)
        return jsonify(admin.to_dict()), 200

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /admin/admins/%s PUT: %s", admin_id, str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /admin/admins/%s PUT: %s", admin_id, str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Xóa admin
@admin_bp.route('/admin/admins/<int:admin_id>', methods=['DELETE'])
@admin_required()
def delete_admin(admin_id):
    try:
        if admin_id < 1:
            return jsonify({'message': 'ID quản trị viên không hợp lệ'}), 400

        admin = Admin.query.get(admin_id)
        if not admin:
            return jsonify({'message': 'Không tìm thấy quản trị viên'}), 404

        # Ngăn admin xóa chính mình
        claims = get_jwt()
        if int(claims['sub']) == admin_id:
            return jsonify({'message': 'Bạn không thể xóa chính mình'}), 403

        # Kiểm tra xem đây có phải admin cuối cùng không
        admin_count = Admin.query.count()
        if admin_count <= 1:
            return jsonify({'message': 'Không thể xóa admin cuối cùng trong hệ thống'}), 403

        db.session.delete(admin)
        db.session.commit()
        logger.info("Xóa admin thành công: admin_id %s", admin_id)
        return '', 204

    except ValueError as ve:
        db.session.rollback()  # Thêm rollback để xử lý lỗi dữ liệu
        logger.error("Lỗi dữ liệu trong /admin/admins/%s DELETE: %s", admin_id, str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        db.session.rollback()  # Thêm rollback để xử lý lỗi chung
        logger.error("Lỗi server trong /admin/admins/%s DELETE: %s", admin_id, str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Thay đổi mật khẩu admin
@admin_bp.route('/me/password', methods=['PUT'])
@jwt_required()
def change_admin_password():
    try:
        claims = get_jwt()
        if claims['type'] != 'ADMIN':
            return jsonify({'message': 'Yêu cầu quyền quản trị viên'}), 403

        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        current_password = data.get('currentPassword')
        new_password = data.get('newPassword')

        if not current_password or not new_password:
            return jsonify({'message': 'Yêu cầu mật khẩu hiện tại và mật khẩu mới'}), 400

        # Kiểm tra độ mạnh của mật khẩu mới
        is_strong, message = is_strong_password(new_password)
        if not is_strong:
            return jsonify({'message': message}), 400

        admin = Admin.query.get(int(claims['sub']))
        if not admin:
            return jsonify({'message': 'Không tìm thấy quản trị viên'}), 404

        if not check_password_hash(admin.password_hash, current_password):
            return jsonify({'message': 'Mật khẩu hiện tại không đúng'}), 401

        admin.password_hash = generate_password_hash(new_password)
        db.session.commit()
        logger.info("Đổi mật khẩu thành công cho admin_id %s", admin.admin_id)
        return jsonify({'message': 'Đổi mật khẩu thành công'}), 200

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /me/password PUT: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /me/password PUT: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Yêu cầu đặt lại mật khẩu (gửi email với mã xác nhận 6 chữ số)
@admin_bp.route('/admin/reset-password/request', methods=['POST'])
def request_password_reset():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        email = data.get('email')
        if not email:
            return jsonify({'message': 'Yêu cầu nhập email'}), 400

        # Kiểm tra định dạng email
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            return jsonify({'message': 'Định dạng email không hợp lệ'}), 400

        admin = Admin.query.filter_by(email=email).first()
        if not admin:
            return jsonify({'message': 'Không tìm thấy quản trị viên với email này'}), 404

        # Tạo mã xác nhận 6 chữ số
        reset_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
        expiry = datetime.utcnow() + timedelta(minutes=30)  # Mã có hiệu lực 30 phút

        # Hash mã xác nhận trước khi lưu
        hashed_code = generate_password_hash(reset_code, method='pbkdf2:sha256')

        # Lưu mã đã hash và thời gian hết hạn
        admin.reset_token = hashed_code
        admin.reset_token_expiry = expiry
        db.session.commit()

        # Kiểm tra cấu hình email
        sender = current_app.config.get('MAIL_DEFAULT_SENDER')
        if not sender:
            logger.error("MAIL_DEFAULT_SENDER chưa được cấu hình")
            return jsonify({'message': 'Lỗi cấu hình email server'}), 500

        # Gửi email chứa mã xác nhận
        try:
            msg = Message(
                subject='Mã xác nhận đặt lại mật khẩu ký túc xá',
                sender=sender,
                recipients=[email],
                html="""Xin chào {full_name},

                Bạn đã yêu cầu đặt lại mật khẩu. Mã xác nhận của bạn là: <b>{reset_code}</b><br><br>

                Mã này có hiệu lực trong 30 phút. Vui lòng nhập mã vào ứng dụng để tiếp tục.

                Nếu bạn không yêu cầu đặt lại mật khẩu, vui lòng bỏ qua email này.

                Trân trọng,
                Hệ thống Ký túc xá""".format(full_name=admin.full_name or "Quản trị viên", reset_code=reset_code)
            )
            logger.debug("Chuẩn bị gửi email tới %s từ %s", email, sender)
            mail.send(msg)
            logger.info("Email với mã xác nhận đã gửi tới %s", email)
        except Exception as e:
            db.session.rollback()
            logger.error("Gửi email thất bại: %s", str(e))
            return jsonify({
                'message': 'Tạo mã xác nhận thành công nhưng gửi email thất bại. Vui lòng thử lại sau.',
                'error': str(e)
            }), 201

        return jsonify({'message': 'Mã xác nhận đã được gửi qua email'}), 200

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /admin/reset-password/request POST: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /admin/reset-password/request POST: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

# Đặt lại mật khẩu (không cần mã nếu đã xác minh)
@admin_bp.route('/admin/reset-password', methods=['POST'])
def reset_password():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        email = data.get('email')
        new_password = data.get('newPassword')
        code = data.get('code')  # Thêm trường code từ request body
        if not email or not new_password or not code:
            return jsonify({'message': 'Yêu cầu nhập email, mật khẩu mới và mã xác nhận'}), 400

        # Kiểm tra định dạng email
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            return jsonify({'message': 'Định dạng email không hợp lệ'}), 400

        # Kiểm tra định dạng mã xác nhận (giả sử mã là 6 chữ số)
        if not isinstance(code, str) or not code.isdigit() or len(code) != 6:
            return jsonify({'message': 'Mã xác nhận phải là chuỗi 6 chữ số'}), 400

        # Kiểm tra độ mạnh của mật khẩu
        is_strong, message = is_strong_password(new_password)
        if not is_strong:
            return jsonify({'message': message}), 400

        admin = Admin.query.filter_by(email=email).first()
        if not admin:
            return jsonify({'message': 'Không tìm thấy quản trị viên với email này'}), 404

        if not admin.reset_token or not admin.reset_token_expiry:
            return jsonify({'message': 'Tài khoản chưa được xác minh để đặt lại mật khẩu'}), 400

        if admin.reset_token_expiry < datetime.utcnow():
            return jsonify({'message': 'Mã xác nhận đã hết hạn'}), 400

        # Kiểm tra mã xác nhận nhập vào có khớp với reset_token (hashed)
        if not check_password_hash(admin.reset_token, code):
            return jsonify({'message': 'Mã xác nhận không chính xác'}), 400

        # Đặt lại mật khẩu và xóa mã xác nhận
        admin.password_hash = generate_password_hash(new_password)
        admin.reset_token = None
        admin.reset_token_expiry = None
        db.session.commit()

        logger.info("Đặt lại mật khẩu thành công cho admin_id %s với email %s", admin.admin_id, email)
        return jsonify({'message': 'Đặt lại mật khẩu thành công'}), 200

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /admin/reset-password POST với email %s: %s", email or "không xác định", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /admin/reset-password POST với email %s: %s", email or "không xác định", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500