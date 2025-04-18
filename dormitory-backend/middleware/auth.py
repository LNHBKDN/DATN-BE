from flask_jwt_extended import jwt_required, get_jwt, JWTError
from functools import wraps
from flask import jsonify
from models.user import User
from models.token_blacklist import TokenBlacklist
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger(__name__)

def admin_required():
    """Decorator yêu cầu quyền admin với kiểm tra blacklist."""
    def wrapper(fn):
        @wraps(fn)
        @jwt_required()
        def decorator(*args, **kwargs):
            try:
                user_id = get_jwt_identity()
                logger.debug(f"Checking admin token for user_id: {user_id}")

                user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
                if not user:
                    logger.warning(f"User not found or deleted: {user_id}")
                    return jsonify({'message': 'Không tìm thấy người dùng'}), 404

                if user.role != 'ADMIN':
                    logger.warning(f"Non-admin user attempted access: {user_id}")
                    return jsonify({'message': 'Yêu cầu quyền quản trị viên'}), 403

                logger.debug(f"Admin check passed for user: {user_id}")
                return fn(*args, **kwargs)

            except JWTError as e:
                logger.error(f"JWT error: {str(e)}")
                return jsonify({'message': 'Token không hợp lệ hoặc thiếu', 'error': str(e)}), 422
            except SQLAlchemyError as e:
                logger.error(f"Database error in admin_required: {str(e)}")
                return jsonify({'message': 'Lỗi database'}), 500

        return decorator
    return wrapper

def user_required():
    """Decorator yêu cầu quyền user với kiểm tra blacklist."""
    def wrapper(fn):
        @wraps(fn)
        @jwt_required()
        def decorator(*args, **kwargs):
            try:
                user_id = get_jwt_identity()
                logger.debug(f"Checking user token for user_id: {user_id}")

                user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
                if not user:
                    logger.warning(f"User not found or deleted: {user_id}")
                    return jsonify({'message': 'Không tìm thấy người dùng'}), 404

                logger.debug(f"User check passed for user: {user_id}")
                return fn(*args, **kwargs)

            except JWTError as e:
                logger.error(f"JWT error: {str(e)}")
                return jsonify({'message': 'Token không hợp lệ hoặc thiếu', 'error': str(e)}), 422
            except SQLAlchemyError as e:
                logger.error(f"Database error in user_required: {str(e)}")
                return jsonify({'message': 'Lỗi database'}), 500

        return decorator
    return wrapper