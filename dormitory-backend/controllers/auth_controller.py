from flask import Blueprint, request, jsonify, current_app, render_template
from flask_jwt_extended import verify_jwt_in_request, create_access_token, create_refresh_token, jwt_required, get_jwt_identity, get_jwt, set_refresh_cookies, unset_jwt_cookies, decode_token
from werkzeug.security import check_password_hash, generate_password_hash
from models.user import User
from models.admin import Admin
from models.contract import Contract
from models.token_blacklist import TokenBlacklist
from models.refresh_tokens import RefreshToken  
from extensions import db, mail
from datetime import datetime, timedelta, timezone
import secrets
from functools import wraps
from flask_mail import Message
import re
import logging
import time

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

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
        now = datetime.now(timezone.utc)
        access_token = create_access_token(
            identity=str(admin.admin_id),
            additional_claims={'type': 'ADMIN'},
            fresh=False,
            expires_delta=current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
        )
        refresh_token = create_refresh_token(
            identity=str(admin.admin_id),
            additional_claims={'type': 'ADMIN'},
            expires_delta=current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
        )
        return {
            'access_token': access_token,
            'id': admin.admin_id,
            'type': 'ADMIN',
            'refresh_token': refresh_token
        }, 200
    return None

def authenticate_user(email, password):
    """Authenticate a User using email."""
    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password_hash, password):
        now = datetime.now(timezone.utc)
        access_token = create_access_token(
            identity=str(user.user_id),
            additional_claims={'type': 'USER'},
            fresh=False,
            expires_delta=current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
        )
        refresh_token = create_refresh_token(
            identity=str(user.user_id),
            additional_claims={'type': 'USER'},
            expires_delta=current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
        )
        return {
            'access_token': access_token,
            'id': user.user_id,
            'type': 'USER',
            'refresh_token': refresh_token
        }, 200
    return None

def execute_with_retry(operation, max_retries=3, delay=1):
    """Execute a database operation with retry logic."""
    for attempt in range(max_retries):
        try:
            return operation()
        except Exception as e:
            if "Lost connection to MySQL server" in str(e) and attempt < max_retries - 1:
                logger.warning("Connection lost, retrying (%d/%d): %s", attempt + 1, max_retries, str(e))
                time.sleep(delay * (2 ** attempt))
                db.session.rollback()
                continue
            raise e

@auth_bp.route('/auth/admin/login', methods=['POST'])
def admin_login():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        username = data.get('username')
        password = data.get('password')
        remember_me = data.get('remember_me', False)
        
        if not username or not password:
            return jsonify({'message': 'Thiếu username hoặc mật khẩu'}), 400
        
        result = authenticate_admin(username, password)
        if result:
            access_token = result[0]['access_token']
            refresh_token = result[0]['refresh_token']  # Always return refresh_token
            admin_id = result[0]['id']
            
            # Store refresh_token in the database
            refresh_token_decoded = decode_token(refresh_token)
            refresh_jti = refresh_token_decoded['jti']
            expires_at = datetime.now(timezone.utc) + current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
            refresh_token_entry = RefreshToken(
                jti=refresh_jti,
                admin_id=admin_id,
                type='ADMIN',
                expires_at=expires_at,
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(refresh_token_entry)
            execute_with_retry(lambda: db.session.commit())

            logger.info("Admin login successful: admin_id %s", admin_id)
            
            response = jsonify({
                'access_token': access_token,
                'refresh_token': refresh_token,
                'id': admin_id,
                'type': 'ADMIN'
            })
            if remember_me:
                set_refresh_cookies(response, refresh_token)
            else:
                unset_jwt_cookies(response)
            return response, result[1]
        
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
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ hoặc thiếu'}), 400

        email = data.get('email')
        password = data.get('password')
        remember_me = data.get('remember_me', False)
        fcm_token = data.get('fcm_token')  # Thêm fcm_token
        
        if not email:
            return jsonify({'message': 'Yêu cầu nhập email'}), 400
        if not password:
            return jsonify({'message': 'Yêu cầu nhập mật khẩu'}), 400

        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            return jsonify({'message': 'Định dạng email không hợp lệ'}), 400
        
        user = User.query.filter_by(email=email, is_deleted=False).first()
        if not user:
            logger.warning("User login failed: email %s not found or deleted", email)
            return jsonify({'message': 'Invalid email'}), 401
        
        if not check_password_hash(user.password_hash, password):
            logger.warning("User login failed: invalid password for email %s", email)
            return jsonify({'message': 'Invalid password'}), 401

        contract = Contract.query.filter_by(
            user_id=user.user_id,
            is_deleted=False
        ).first()
        if not contract:
            logger.warning("User login failed: user %s has no contract", user.email)
            return jsonify({'message': 'Bạn chưa tạo hợp đồng, chưa thể đăng nhập vào ứng dụng'}), 403
        
        if contract.calculated_status != 'ACTIVE':
            logger.warning("User login failed: contract for user %s is not active, status: %s", user.email, contract.calculated_status)
            return jsonify({'message': 'Hợp đồng của bạn chưa ở trạng thái ACTIVE, không thể đăng nhập'}), 403

        # Cập nhật fcm_token nếu có
        if fcm_token:
            user.fcm_token = fcm_token
            db.session.commit()
            logger.info(f"Updated FCM token for user_id={user.user_id}")

        access_token = create_access_token(
            identity=str(user.user_id),
            additional_claims={'type': 'USER'},
            fresh=False,
            expires_delta=current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
        )
        refresh_token = create_refresh_token(  # Always create refresh_token
            identity=str(user.user_id),
            additional_claims={'type': 'USER'},
            expires_delta=current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
        )
        
        # Store refresh_token in the database
        refresh_token_decoded = decode_token(refresh_token)
        refresh_jti = refresh_token_decoded['jti']
        expires_at = datetime.now(timezone.utc) + current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
        refresh_token_entry = RefreshToken(
            jti=refresh_jti,
            user_id=user.user_id,
            type='USER',
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(refresh_token_entry)
        execute_with_retry(lambda: db.session.commit())

        logger.info("User login successful: user_id %s", user.user_id)
        
        response = jsonify({
            'access_token': access_token,
            'refresh_token': refresh_token,  # Always return refresh_token
            'id': user.user_id,
            'type': 'USER'
        })
        if remember_me:
            set_refresh_cookies(response, refresh_token)
        else:
            unset_jwt_cookies(response)
        return response, 200

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /auth/user/login: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /auth/user/login: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

@auth_bp.route('/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh an access token using a refresh token."""
    try:
        claims = get_jwt()
        jti = claims['jti']
        user_id = get_jwt_identity()
        user_type = claims['type']

        refresh_token = RefreshToken.query.filter_by(jti=jti, type=user_type).first()
        if not refresh_token:
            return jsonify({'message': 'Refresh token không hợp lệ'}), 401
        if refresh_token.revoked_at:
            return jsonify({'message': 'Refresh token đã bị thu hồi'}), 401
        if refresh_token.expires_at < datetime.now(timezone.utc):
            return jsonify({'message': 'Refresh token đã hết hạn'}), 401

        if user_type == 'USER':
            user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
            if not user:
                return jsonify({'message': 'Người dùng không tồn tại hoặc đã bị xóa'}), 404
        else:
            admin = Admin.query.get(user_id)
            if not admin:
                return jsonify({'message': 'Quản trị viên không tồn tại'}), 404

        new_access_token = create_access_token(
            identity=user_id,
            additional_claims={'type': user_type},
            fresh=False,
            expires_delta=current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
        )

        refresh_token.revoked_at = datetime.now(timezone.utc)
        new_refresh_token = create_refresh_token(
            identity=user_id,
            additional_claims={'type': user_type},
            expires_delta=current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
        )
        new_refresh_jti = get_jwt()['jti']
        new_expires_at = datetime.now(timezone.utc) + current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
        new_refresh_token_entry = RefreshToken(
            jti=new_refresh_jti,
            user_id=user_id if user_type == 'USER' else None,
            admin_id=user_id if user_type == 'ADMIN' else None,
            type=user_type,
            expires_at=new_expires_at,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(new_refresh_token_entry)
        execute_with_retry(lambda: db.session.commit())

        logger.info("Token refreshed successfully for %s_id %s", user_type.lower(), user_id)
        
        response = jsonify({
            'access_token': new_access_token,
            'refresh_token': new_refresh_token
        })
        set_refresh_cookies(response, new_refresh_token)
        return response, 200

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /auth/refresh: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /auth/refresh: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

@auth_bp.route('/auth/logout', methods=['POST'])
@jwt_required(optional=True)
def logout():
    """Log out a user or admin by adding tokens to the blacklist."""
    try:
        verify_jwt_in_request(optional=True)
        access_jti = None
        refresh_jti = None

        jwt_data = get_jwt()
        if jwt_data:
            access_jti = jwt_data['jti']
            access_expires_at = datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
            access_token = TokenBlacklist(jti=access_jti, expires_at=access_expires_at)
            db.session.add(access_token)

        refresh_token = request.cookies.get('refresh_token')
        if refresh_token:
            refresh_token_decoded = decode_token(refresh_token)
            refresh_jti = refresh_token_decoded['jti']
            refresh_token_entry = RefreshToken.query.filter_by(jti=refresh_jti).first()
            if refresh_token_entry and not refresh_token_entry.revoked_at:
                refresh_token_entry.revoked_at = datetime.now(timezone.utc)
        
        execute_with_retry(lambda: db.session.commit())

        logger.info("Token blacklisted successfully: access_jti %s, refresh_jti %s", access_jti or "none", refresh_jti or "none")
        
        response = jsonify({'message': 'Đăng xuất thành công'})
        unset_jwt_cookies(response)
        return response, 200

    except ValueError as ve:
        logger.error("Lỗi dữ liệu trong /auth/logout: %s", str(ve))
        return jsonify({'message': 'Dữ liệu không hợp lệ', 'error': str(ve)}), 400
    except Exception as e:
        logger.error("Lỗi server trong /auth/logout: %s", str(e))
        return jsonify({'message': 'Lỗi server', 'error': str(e)}), 500

@auth_bp.route('/auth/forgot-password', methods=['POST'])
def forgot_password():
    """Handle forgot password requests by sending a reset code via email."""
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
        expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
        hashed_code = generate_password_hash(reset_code, method='pbkdf2:sha256')

        user_or_admin.reset_token = hashed_code
        user_or_admin.reset_token_expiry = expiry
        user_or_admin.reset_attempts = 0

        execute_with_retry(lambda: db.session.commit())

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
    """Reset a user or admin password using a reset code and revoke all refresh tokens."""
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
            if not admin.reset_token_expiry or admin.reset_token_expiry < datetime.now(timezone.utc):
                admin.reset_attempts = 0
                admin.reset_token = None
                admin.reset_token_expiry = None
                execute_with_retry(lambda: db.session.commit())
                return jsonify({'message': 'Mã xác nhận đã hết hạn hoặc không hợp lệ'}), 400
            if admin.reset_attempts >= 3:
                admin.reset_token = None
                admin.reset_token_expiry = None
                admin.reset_attempts = 0
                execute_with_retry(lambda: db.session.commit())
                logger.warning("Admin %s vượt quá số lần thử mã xác nhận", admin.admin_id)
                return jsonify({'message': 'Bạn đã nhập sai mã quá 3 lần. Vui lòng yêu cầu mã xác nhận mới'}), 400
            if not check_password_hash(admin.reset_token, code):
                admin.reset_attempts += 1
                execute_with_retry(lambda: db.session.commit())
                logger.warning("Admin %s nhập sai mã xác nhận, lần thử %s", admin.admin_id, admin.reset_attempts)
                return jsonify({'message': f'Mã xác nhận không chính xác. Bạn còn {3 - admin.reset_attempts} lần thử.'}), 400
            
            refresh_tokens = RefreshToken.query.filter_by(admin_id=admin.admin_id, type='ADMIN', revoked_at=None).all()
            for token in refresh_tokens:
                token.revoked_at = datetime.now(timezone.utc)

            admin.password_hash = generate_password_hash(new_password)
            admin.reset_token = None
            admin.reset_token_expiry = None
            admin.reset_attempts = 0
            execute_with_retry(lambda: db.session.commit())
            logger.info("Mật khẩu admin %s đã được đặt lại", admin.admin_id)

            reset_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
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
            if not user.reset_token_expiry or user.reset_token_expiry < datetime.now(timezone.utc):
                user.reset_attempts = 0
                user.reset_token = None
                user.reset_token_expiry = None
                execute_with_retry(lambda: db.session.commit())
                return jsonify({'message': 'Mã xác nhận đã hết hạn hoặc không hợp lệ'}), 400
            if user.reset_attempts >= 3:
                user.reset_token = None
                user.reset_token_expiry = None
                user.reset_attempts = 0
                execute_with_retry(lambda: db.session.commit())
                logger.warning("User %s vượt quá số lần thử mã xác nhận", user.user_id)
                return jsonify({'message': 'Bạn đã nhập sai mã quá 3 lần. Vui lòng yêu cầu mã xác nhận mới'}), 400
            if not check_password_hash(user.reset_token, code):
                user.reset_attempts += 1
                execute_with_retry(lambda: db.session.commit())
                logger.warning("User %s nhập sai mã xác nhận, lần thử %s", user.user_id, user.reset_attempts)
                return jsonify({'message': f'Mã xác nhận không chính xác. Bạn còn {3 - user.reset_attempts} lần thử.'}), 400
            
            refresh_tokens = RefreshToken.query.filter_by(user_id=user.user_id, type='USER', revoked_at=None).all()
            for token in refresh_tokens:
                token.revoked_at = datetime.now(timezone.utc)

            user.password_hash = generate_password_hash(new_password)
            user.reset_token = None
            user.reset_token_expiry = None
            user.reset_attempts = 0
            execute_with_retry(lambda: db.session.commit())
            logger.info("Mật khẩu user %s đã được đặt lại", user.user_id)

            reset_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
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