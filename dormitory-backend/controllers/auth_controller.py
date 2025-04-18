from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from werkzeug.security import check_password_hash, generate_password_hash
from models.user import User
from models.admin import Admin
from models.token_blacklist import TokenBlacklist
from extensions import db, mail
from datetime import datetime, timedelta
import secrets
from functools import wraps
from flask_mail import Message
import re
import logging
from flask import render_template
# Thiết lập logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# Hàm kiểm tra độ mạnh của mật khẩu
def is_strong_password(password):
    """Check if the password meets strength requirements."""
    if not isinstance(password, str):
        return False, "Mật khẩu phải là chuỗi ký tự"
    if len(password) < 12:
        return False, "Mật khẩu phải có ít nhất 12 ký tự"
    if not re.search(r"[A-Z]", password):
        return False, "Mật khẩu phải chứa ít nhất một chữ cái in hoa"
    if not re.search(r"[a-z]", password):
        return False, "Mật khẩu phải chứa ít nhất một chữ cái thường"
    if not re.search(r"[0-9]", password):
        return False, "Mật khẩu phải chứa ít nhất một số"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Mật khẩu phải chứa ít nhất một ký tự đặc biệt"
    return True, ""

def authenticate_admin(username, password):
    """Authenticate an Admin using username."""
    admin = Admin.query.filter_by(username=username).first()
    if admin and check_password_hash(admin.password_hash, password):
        access_token = create_access_token(identity=str(admin.admin_id), additional_claims={'type': 'ADMIN'})
        return {
            'access_token': access_token,
            'id': admin.admin_id,
            'type': 'ADMIN'
        }, 200
    return None

def authenticate_user(email, password):
    """Authenticate a User using email."""
    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password_hash, password):
        access_token = create_access_token(identity=str(user.user_id), additional_claims={'type': 'USER'})
        return {
            'access_token': access_token,
            'id': user.user_id,
            'type': 'USER'
        }, 200
    return None

@auth_bp.route('/auth/admin/login', methods=['POST'])
def admin_login():
    """Authenticate an admin using username and return a JWT token."""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'message': 'Thiếu username hoặc mật khẩu'}), 400
        
        result = authenticate_admin(username, password)
        if result:
            logger.info("Admin login successful: admin_id %s", result[0]['id'])
            return jsonify(result[0]), result[1]
        
        logger.warning("Admin login failed: invalid credentials for username %s", username)
        return jsonify({'message': 'Thông tin đăng nhập không hợp lệ'}), 401

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /auth/admin/login: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /auth/admin/login: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

@auth_bp.route('/auth/user/login', methods=['POST'])
def user_login():
    """Authenticate a user using email and return a JWT token."""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        email = data.get('email')
        password = data.get('password')
        
        if not email:
            return jsonify({'message': 'Yêu cầu nhập email'}), 400
        if not password:
            return jsonify({'message': 'Yêu cầu nhập mật khẩu'}), 400

        # Kiểm tra định dạng email
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            return jsonify({'message': 'Định dạng email không hợp lệ'}), 400
        
        result = authenticate_user(email, password)
        if result:
            logger.info("User login successful: user_id %s", result[0]['id'])
            return jsonify(result[0]), result[1]
        
        logger.warning("User login failed: invalid credentials for email %s", email)
        return jsonify({'message': 'Thông tin đăng nhập không hợp lệ'}), 401

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /auth/user/login: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /auth/user/login: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

@auth_bp.route('/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    """Log out a user or admin by adding the token to the blacklist."""
    try:
        # Lấy jti từ token JWT
        jti = get_jwt()['jti']
        expires_at = datetime.utcnow() + current_app.config['JWT_ACCESS_TOKEN_EXPIRES']

        # Kiểm tra xem jti đã tồn tại trong danh sách đen chưa
        existing_token = TokenBlacklist.query.filter_by(jti=jti).first()
        if existing_token:
            logger.info("Token %s đã được vô hiệu hóa trước đó", jti)
            return jsonify({'message': 'Đăng xuất thành công'}), 200

        # Thêm token vào danh sách đen
        token = TokenBlacklist(jti=jti, expires_at=expires_at)
        db.session.add(token)
        db.session.commit()

        logger.info("Token %s đã được thêm vào danh sách đen", jti)
        return jsonify({'message': 'Đăng xuất thành công'}), 200

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /auth/logout: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /auth/logout: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

@auth_bp.route('/auth/forgot-password', methods=['POST'])
def forgot_password():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        email = data.get('email')
        if not email:
            return jsonify({'message': 'Yêu cầu nhập email'}), 400

        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            return jsonify({'message': 'Định dạng email không hợp lệ'}), 400

        user_or_admin = Admin.query.filter_by(email=email).first()
        user_type = 'admin'
        if not user_or_admin:
            user_or_admin = User.query.filter_by(email=email).first()
            user_type = 'user'
        if not user_or_admin:
            return jsonify({'message': 'Không tìm thấy tài khoản với email này'}), 404

        reset_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
        expiry = datetime.utcnow() + timedelta(minutes=30)
        hashed_code = generate_password_hash(reset_code, method='pbkdf2:sha256')

        user_or_admin.reset_token = hashed_code
        user_or_admin.reset_token_expiry = expiry
        user_or_admin.reset_attempts = 0
        db.session.commit()

        sender = current_app.config.get('MAIL_DEFAULT_SENDER')
        if not sender:
            logger.error("MAIL_DEFAULT_SENDER chưa được cấu hình")
            return jsonify({'message': 'Lỗi cấu hình email server'}), 500

        try:
            msg = Message(
                subject='Mã xác nhận đặt lại mật khẩu ký túc xá',
                sender=sender,
                recipients=[email]
            )
            msg.html = render_template('emails/forgot_password.html', reset_code=reset_code)

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

        return jsonify({
            'message': 'Mã xác nhận đã được gửi qua email.',
            'user_type': user_type
        }), 200

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /auth/forgot-password: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /auth/forgot-password: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

@auth_bp.route('/auth/reset-password', methods=['POST'])
def reset_password():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        email = data.get('email')
        new_password = data.get('newPassword')
        code = data.get('code')
        if not email or not new_password or not code:
            return jsonify({'message': 'Yêu cầu nhập email, mật khẩu mới và mã xác nhận'}), 400

        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            return jsonify({'message': 'Định dạng email không hợp lệ'}), 400

        if not isinstance(code, str) or not code.isdigit() or len(code) != 6:
            return jsonify({'message': 'Mã xác nhận phải là chuỗi 6 chữ số'}), 400

        is_strong, message = is_strong_password(new_password)
        if not is_strong:
            return jsonify({'message': message}), 400

        admin = Admin.query.filter_by(email=email).first()
        if admin and admin.reset_token:
            if not admin.reset_token_expiry or admin.reset_token_expiry < datetime.utcnow():
                admin.reset_attempts = 0
                admin.reset_token = None
                admin.reset_token_expiry = None
                db.session.commit()
                return jsonify({'message': 'Mã xác nhận đã hết hạn hoặc không hợp lệ'}), 400
            if admin.reset_attempts >= 3:
                admin.reset_token = None
                admin.reset_token_expiry = None
                admin.reset_attempts = 0
                db.session.commit()
                logger.warning("Admin %s vượt quá số lần thử mã xác nhận", admin.admin_id)
                return jsonify({'message': 'Bạn đã nhập sai mã quá 3 lần. Vui lòng yêu cầu mã xác nhận mới'}), 400
            if not check_password_hash(admin.reset_token, code):
                admin.reset_attempts += 1
                db.session.commit()
                logger.warning("Admin %s nhập sai mã xác nhận, lần thử %s", admin.admin_id, admin.reset_attempts)
                return jsonify({'message': f'Mã xác nhận không chính xác. Bạn còn {3 - admin.reset_attempts} lần thử.'}), 400
            admin.password_hash = generate_password_hash(new_password)
            admin.reset_token = None
            admin.reset_token_expiry = None
            admin.reset_attempts = 0
            db.session.commit()
            logger.info("Mật khẩu admin %s đã được đặt lại", admin.admin_id)

            # Gửi email thông báo đặt lại mật khẩu thành công
            reset_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            login_url = f"{request.host_url}login"
            try:
                msg = Message(
                    subject='Đặt lại mật khẩu thành công',
                    sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                    recipients=[email]
                )
                msg.html = render_template('emails/reset_password_success.html', reset_time=reset_time, login_url=login_url)

                mail.send(msg)
                logger.info("Email thông báo đặt lại mật khẩu gửi tới %s", email)
            except Exception as e:
                logger.error("Gửi email thông báo thất bại: %s", str(e))

            return jsonify({'message': 'Đặt lại mật khẩu thành công'}), 200

        user = User.query.filter_by(email=email).first()
        if user and user.reset_token:
            if not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
                user.reset_attempts = 0
                user.reset_token = None
                user.reset_token_expiry = None
                db.session.commit()
                return jsonify({'message': 'Mã xác nhận đã hết hạn hoặc không hợp lệ'}), 400
            if user.reset_attempts >= 3:
                user.reset_token = None
                user.reset_token_expiry = None
                user.reset_attempts = 0
                db.session.commit()
                logger.warning("User %s vượt quá số lần thử mã xác nhận", user.user_id)
                return jsonify({'message': 'Bạn đã nhập sai mã quá 3 lần. Vui lòng yêu cầu mã xác nhận mới'}), 400
            if not check_password_hash(user.reset_token, code):
                user.reset_attempts += 1
                db.session.commit()
                logger.warning("User %s nhập sai mã xác nhận, lần thử %s", user.user_id, user.reset_attempts)
                return jsonify({'message': f'Mã xác nhận không chính xác. Bạn còn {3 - user.reset_attempts} lần thử.'}), 400
            user.password_hash = generate_password_hash(new_password)
            user.reset_token = None
            user.reset_token_expiry = None
            user.reset_attempts = 0
            db.session.commit()
            logger.info("Mật khẩu user %s đã được đặt lại", user.user_id)

            # Gửi email thông báo đặt lại mật khẩu thành công
            reset_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            login_url = f"{request.host_url}login"
            try:
                msg = Message(
                    subject='Đặt lại mật khẩu thành công',
                    sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                    recipients=[email]
                )
                msg.html = render_template('emails/reset_password_success.html', reset_time=reset_time, login_url=login_url)

                mail.send(msg)
                logger.info("Email thông báo đặt lại mật khẩu gửi tới %s", email)
            except Exception as e:
                logger.error("Gửi email thông báo thất bại: %s", str(e))

            return jsonify({'message': 'Đặt lại mật khẩu thành công'}), 200

        return jsonify({'message': 'Không tìm thấy tài khoản hoặc mã xác nhận không hợp lệ'}), 400

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /auth/reset-password: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /auth/reset-password: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

def admin_required():
    """Decorator to require admin access."""
    def wrapper(fn):
        @wraps(fn)
        @jwt_required()
        def decorator(*args, **kwargs):
            claims = get_jwt()
            if claims.get('type') != 'ADMIN':
                return jsonify({'message': 'Yêu cầu quyền quản trị viên'}), 403
            return fn(*args, **kwargs)
        return decorator
    return wrapper

def user_required():
    """Decorator to require user access."""
    def wrapper(fn):
        @wraps(fn)
        @jwt_required()
        def decorator(*args, **kwargs):
            claims = get_jwt()
            if claims.get('type') != 'USER':
                return jsonify({'message': 'Yêu cầu quyền người dùng'}), 403
            return fn(*args, **kwargs)
        return decorator
    return wrapper