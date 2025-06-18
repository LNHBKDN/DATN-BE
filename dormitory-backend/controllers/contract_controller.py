from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from flask import current_app
from extensions import db
from models.contract import Contract
from models.user import User
from models.room import Room
from models.notification import Notification
from models.notification_recipient import NotificationRecipient
from controllers.auth_controller import admin_required, user_required
from controllers.statistics_controller import snapshot_room_status, save_user_room_snapshot
from datetime import datetime, date, timedelta
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
import logging
from json import JSONEncoder
from dateutil.parser import parse as parse_date
from sqlalchemy.sql import func
import pendulum

from utils.fcm import send_fcm_notification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

contract_bp = Blueprint('contract', __name__)

class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, db.Model):
            return str(obj)
        if hasattr(obj, '__str__'):
            return str(obj)
        return super().default(obj)

def update_contract_status():
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
        db.session.rollback()
        logger.error(f"Error during contract status update: {str(e)}")
        raise

@contract_bp.route('/contracts', methods=['GET'])
@admin_required()
def get_all_contracts():
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        user_id = request.args.get('user_id', type=int)
        email = request.args.get('email', type=str)
        fullname = request.args.get('fullname', type=str)  # Thêm dòng này nếu muốn filter riêng fullname
        keyword = request.args.get('keyword', type=str)    # Thêm dòng này nếu muốn filter chung
        room_id = request.args.get('room_id', type=int)
        status = request.args.get('status', type=str)
        start_date = request.args.get('start_date', type=str)
        end_date = request.args.get('end_date', type=str)
        contract_type = request.args.get('contract_type', type=str)

        filter_params = {
            'user_id': user_id,
            'email': email,
            'fullname': fullname,
            'keyword': keyword,
            'room_id': room_id,
            'status': status,
            'start_date': start_date,
            'end_date': end_date,
            'contract_type': contract_type
        }
        provided_filters = {key: value for key, value in filter_params.items() if value is not None}

        if provided_filters:
            for key, value in provided_filters.items():
                if isinstance(value, str) and not value.strip():
                    return jsonify({
                        'message': f'Tham số {key} không được để trống'
                    }), 400

        query = Contract.query

        # Join với User nếu tìm kiếm theo tên/email/keyword
        if 'keyword' in provided_filters and keyword:
            keyword = keyword.strip()
            query = query.join(User, Contract.user_id == User.user_id).filter(
                db.or_(
                    User.fullname.ilike(f'%{keyword}%'),
                    User.email.ilike(f'%{keyword}%')
                )
            )
        elif 'fullname' in provided_filters and fullname:
            query = query.join(User, Contract.user_id == User.user_id).filter(
                User.fullname.ilike(f'%{fullname.strip()}%')
            )
        elif 'email' in provided_filters and email:
            user = User.query.filter_by(email=email).first()
            if not user:
                return jsonify({'message': 'Không tìm thấy người dùng với email này'}), 404
            query = query.filter_by(user_id=user.user_id)
        elif 'user_id' in provided_filters:
            if not User.query.get(user_id):
                return jsonify({'message': 'Không tìm thấy người dùng'}), 404
            query = query.filter_by(user_id=user_id)

        if 'room_id' in provided_filters:
            if not Room.query.get(room_id):
                return jsonify({'message': 'Không tìm thấy phòng'}), 404
            query = query.filter_by(room_id=room_id)

        if 'status' in provided_filters:
            status = status.upper()
            if status not in ['PENDING', 'ACTIVE', 'EXPIRED', 'TERMINATED']:
                return jsonify({'message': 'Trạng thái hợp đồng không hợp lệ'}), 400
            query = query.filter_by(status=status)

        if 'start_date' in provided_filters:
            try:
                query = query.filter(Contract.start_date >= datetime.strptime(start_date, '%Y-%m-%d').date())
            except ValueError:
                return jsonify({'message': 'Định dạng start_date không hợp lệ (YYYY-MM-DD)'}), 400

        if 'end_date' in provided_filters:
            try:
                query = query.filter(Contract.end_date <= datetime.strptime(end_date, '%Y-%m-%d').date())
            except ValueError:
                return jsonify({'message': 'Định dạng end_date không hợp lệ (YYYY-MM-DD)'}), 400

        if 'contract_type' in provided_filters:
            contract_type = contract_type.upper()
            if contract_type not in ['SHORT_TERM', 'LONG_TERM']:
                return jsonify({'message': 'Loại hợp đồng không hợp lệ'}), 400
            query = query.filter_by(contract_type=contract_type)

        contracts = query.paginate(page=page, per_page=limit)
        logger.info(f"Retrieved {contracts.total} contracts for admin")
        return jsonify({
            'contracts': [contract.to_dict() for contract in contracts.items],
            'total': contracts.total,
            'pages': contracts.pages,
            'current_page': contracts.page
        }), 200
    except Exception as e:
        logger.error(f"Error in get_all_contracts: {str(e)}")
        return jsonify({'message': 'Lỗi server khi lấy danh sách hợp đồng'}), 500

@contract_bp.route('/contracts/<int:contract_id>', methods=['GET'])
@jwt_required()
def get_contract_by_id(contract_id):
    try:
        identity = get_jwt_identity()
        claims = get_jwt()
        if not identity:
            logger.error("No JWT identity found")
            return jsonify({'message': 'Token không hợp lệ hoặc thiếu thông tin'}), 401

        if isinstance(identity, str):
            try:
                identity_dict = {
                    "id": int(identity),
                    "type": claims.get('type', 'USER')
                }
            except ValueError:
                logger.error(f"Invalid identity format, cannot convert to int: {identity}")
                return jsonify({'message': 'Token sai định dạng'}), 401
        else:
            logger.error(f"JWT identity is not a string: {identity}")
            return jsonify({'message': 'Token sai định dạng'}), 401

        if identity_dict['type'] not in ['ADMIN', 'USER']:
            logger.error(f"Invalid type in identity: {identity_dict}")
            return jsonify({'message': 'Token chứa type không hợp lệ'}), 401

        contract = Contract.query.get(contract_id)
        if not contract:
            logger.info(f"Contract {contract_id} not found")
            return jsonify({'message': 'Không tìm thấy hợp đồng'}), 404

        if identity_dict['type'] == 'USER' and contract.user_id != identity_dict['id']:
            logger.info(f"User {identity_dict['id']} unauthorized to view contract {contract_id}")
            return jsonify({'message': 'Bạn không có quyền xem hợp đồng này'}), 403

        try:
            contract_data = contract.to_dict()
            contract_data['status'] = contract.calculated_status
            logger.debug(f"Contract data before jsonify: {contract_data}")
            if contract_data['room_details']:
                logger.debug(f"Room details: {contract_data['room_details']}")
            if contract_data['user_details']:
                logger.debug(f"User details: {contract_data['user_details']}")
        except Exception as dict_error:
            logger.error(f"Failed to serialize contract {contract_id}: {str(dict_error)}")
            return jsonify({'message': 'Lỗi khi lấy dữ liệu hợp đồng', 'error': str(dict_error)}), 500

        try:
            response = jsonify(contract_data)
            response.json_encoder = CustomJSONEncoder
        except Exception as json_error:
            logger.error(f"Failed to jsonify contract data for {contract_id}: {str(json_error)}")
            return jsonify({'message': 'Lỗi khi trả về dữ liệu hợp đồng', 'error': str(json_error)}), 500

        logger.info(f"Retrieved contract {contract_id} for user {identity_dict['id']}")
        return response, 200
    except Exception as e:
        logger.error(f"Unexpected error in get_contract_by_id for contract {contract_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server khi lấy chi tiết hợp đồng', 'error': str(e)}), 500

@contract_bp.route('/admin/contracts', methods=['POST'])
@admin_required()
def create_contract():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

        email = data.get('email')
        room_name = data.get('room_name')
        area_id = data.get('area_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        contract_type = data.get('contract_type')

        if not all([email, room_name, area_id, start_date, end_date, contract_type]):
            return jsonify({'message': 'Yêu cầu email, room_name, area_id, start_date, end_date và contract_type'}), 400

        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({'message': 'Không tìm thấy người dùng với email này'}), 404
        user_id = user.user_id

        room = Room.query.filter_by(name=room_name, area_id=area_id).first()
        if not room:
            return jsonify({'message': 'Không tìm thấy phòng với tên và khu vực này'}), 404
        room_id = room.room_id

        logger.info(f"Creating contract for room_id={room_id}, room_name={room_name}, is_deleted={room.is_deleted}")

        try:
            start_date = parse_date(start_date).date()
            end_date = parse_date(end_date).date()
            if start_date >= end_date:
                return jsonify({'message': 'Ngày bắt đầu phải trước ngày kết thúc'}), 400
            today = pendulum.now('Asia/Ho_Chi_Minh').date()
            if start_date < today:
                return jsonify({'message': 'Ngày bắt đầu không được là ngày trong quá khứ'}), 400
        except ValueError:
            return jsonify({'message': 'Định dạng ngày không hợp lệ (YYYY-MM-DD)'}), 400

        if contract_type not in ['SHORT_TERM', 'LONG_TERM']:
            return jsonify({'message': 'Loại hợp đồng phải là SHORT_TERM hoặc LONG_TERM'}), 400

        existing_contract = Contract.query.filter_by(user_id=user_id).first()
        if existing_contract:
            return jsonify({'message': 'Người dùng đã có hợp đồng, không thể tạo hợp đồng mới'}), 400

        room = Room.query.with_for_update().get(room_id)
        if room.current_person_number >= room.capacity:
            return jsonify({'message': 'Phòng đã đầy'}), 400

        contract = Contract(
            user_id=user_id,
            room_id=room_id,
            start_date=start_date,
            end_date=end_date,
            contract_type=contract_type,
            status='PENDING' if start_date > today else 'ACTIVE'
        )
        db.session.add(contract)

        if contract.status == 'ACTIVE':
            room.current_person_number += 1
            room.status = 'OCCUPIED' if room.current_person_number >= room.capacity else 'AVAILABLE'
            logger.debug(f"Updated current_person_number for room {room_id}: {room.current_person_number}")

        db.session.commit()
        logger.info(f"Contract created with contract_id={contract.contract_id}")

        try:
            notification = Notification(
                title="Hợp đồng mới đã được tạo",
                message="Hợp đồng của bạn đã được tạo thành công. Vui lòng xem chi tiết trong phần cài đặt.",
                target_type="SYSTEM",
                target_id=user_id,
                related_entity_type="CONTRACT",
                related_entity_id=contract.contract_id,
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
                    'related_entity_type': 'CONTRACT',
                    'related_entity_id': str(contract.contract_id)
                }
            )
            db.session.commit()
            logger.info(f"Notification created for user {user_id}, notification_id={notification.id}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to create SYSTEM notification for user {user_id}, contract {contract.contract_id}: {str(e)}")

        try:
            current_time = pendulum.now('Asia/Ho_Chi_Minh')
            year = current_time.year
            month = current_time.month
            success_room = snapshot_room_status(year, month, room_id=room_id)
            success_user = save_user_room_snapshot(year, month, room_id=room_id)
            if success_room and success_user:
                logger.info(f"Successfully ran snapshots for {year}-{month}, room_id={room_id}, is_deleted={room.is_deleted} after contract creation {contract.contract_id}")
            else:
                logger.error(f"Failed to run snapshots for {year}-{month}, room_id={room_id}, is_deleted={room.is_deleted} after contract creation {contract.contract_id}: room={success_room}, user={success_user}")
        except Exception as e:
            logger.error(f"Error running snapshots after contract creation {contract.contract_id}, room_id={room_id}, is_deleted={room.is_deleted}: {str(e)}")

        return jsonify(contract.to_dict()), 201
    except IntegrityError:
        db.session.rollback()
        logger.error(f"Failed to create contract for email={email}, room_name={room_name}")
        return jsonify({'message': 'Xung đột khi tạo hợp đồng, vui lòng thử lại'}), 409
    except ValueError as e:
        db.session.rollback()
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in create_contract: {str(e)}")
        return jsonify({'message': 'Lỗi server khi tạo hợp đồng'}), 500

@contract_bp.route('/admin/contracts/<int:contract_id>', methods=['PUT'])
@admin_required()
def update_contract(contract_id):
    try:
        contract = Contract.query.get(contract_id)
        if not contract:
            logger.info(f"Contract {contract_id} not found")
            return jsonify({'message': 'Không tìm thấy hợp đồng'}), 404

        data = request.get_json()
        if not data:
            logger.error("No JSON data provided")
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

        original_room_id = contract.room_id
        original_status = contract.status
        room_ids_to_update = {original_room_id}

        if 'email' in data:
            user = User.query.filter_by(email=data['email']).first()
            if not user:
                logger.info(f"User with email {data['email']} not found")
                return jsonify({'message': 'Không tìm thấy người dùng'}), 404
            contract.user_id = user.user_id

        if 'room_name' in data or 'area_id' in data:
            room_name = data.get('room_name', contract.room.to_dict()['name'])
            area_id = data.get('area_id', contract.room.area_id)
            room = Room.query.filter_by(name=room_name, area_id=area_id).first()
            if not room:
                logger.info(f"Room with name {room_name} and area_id {area_id} not found")
                return jsonify({'message': 'Không tìm thấy phòng với tên và khu vực này'}), 404
            if room.room_id != original_room_id:
                room_ids_to_update.add(room.room_id)
                contract.room_id = room.room_id

        if 'contract_type' in data:
            contract_type = data['contract_type'].upper()
            if contract_type not in ['SHORT_TERM', 'LONG_TERM']:
                logger.error(f'Invalid contract_type: {contract_type}')
                return jsonify({'message': 'Loại hợp đồng phải là SHORT_TERM hoặc LONG_TERM'}), 400
            contract.contract_type = contract_type

        if 'status' in data:
            status = data['status'].upper()
            valid_statuses = ['PENDING', 'ACTIVE', 'EXPIRED', 'TERMINATED']
            if status not in valid_statuses:
                logger.error(f'Invalid status: {status}')
                return jsonify({'message': 'Trạng thái hợp đồng không hợp lệ'}), 400
            if contract.status == 'TERMINATED' and status in ['PENDING', 'ACTIVE']:
                logger.error(f'Cannot change TERMINATED contract {contract_id} to {status}')
                return jsonify({'message': 'Không thể chuyển hợp đồng đã TERMINATED sang PENDING hoặc ACTIVE'}), 400
            contract.status = status

        if 'start_date' in data:
            try:
                new_start_date = parse_date(data['start_date']).date()
                today = pendulum.now('Asia/Ho_Chi_Minh').date()
                if new_start_date < today:
                    return jsonify({'message': 'Ngày bắt đầu không được là ngày trong quá khứ'}), 400
                contract.start_date = new_start_date
            except ValueError:
                logger.error(f'Invalid start_date format: {data["start_date"]}')
                return jsonify({'message': 'Định dạng start_date không hợp lệ (YYYY-MM-DD)'}), 400

        if 'end_date' in data:
            try:
                contract.end_date = parse_date(data['end_date']).date()
            except ValueError:
                logger.error(f'Invalid end_date format: {data["end_date"]}')
                return jsonify({'message': 'Định dạng end_date không hợp lệ (YYYY-MM-DD)'}), 400

        if contract.start_date and contract.end_date and contract.start_date >= contract.end_date:
            logger.error(f'Start date {contract.start_date} is not before end date {contract.end_date}')
            return jsonify({'message': 'Ngày bắt đầu phải trước ngày kết thúc'}), 400

        try:
            if not contract.start_date or not contract.end_date:
                logger.error(f'Contract {contract_id} has invalid start_date or end_date')
                return jsonify({'message': 'Dữ liệu hợp đồng không hợp lệ, thiếu ngày bắt đầu hoặc kết thúc'}), 400
            contract.update_status()
            logger.debug(f'Updated status for contract {contract_id} to {contract.status}')
        except Exception as update_error:
            logger.error(f'Failed to update status for contract {contract_id}: {str(update_error)}')
            return jsonify({'message': 'Lỗi khi cập nhật trạng thái hợp đồng', 'error': str(update_error)}), 500

        for room_id in room_ids_to_update:
            room = Room.query.with_for_update().get(room_id)
            if contract.status == 'ACTIVE' and original_status != 'ACTIVE':
                room.current_person_number += 1
            elif contract.status != 'ACTIVE' and original_status == 'ACTIVE':
                room.current_person_number = max(0, room.current_person_number - 1)
            room.status = 'OCCUPIED' if room.current_person_number >= room.capacity else 'AVAILABLE'
            logger.debug(f'Updated current_person_number for room {room_id}: {room.current_person_number}')

        try:
            db.session.commit()
            logger.info(f'Contract {contract_id} updated successfully')
        except ValueError as e:
            db.session.rollback()
            logger.error(f'Validation error updating contract {contract_id}: {str(e)}')
            return jsonify({'message': str(e)}), 400
        except IntegrityError as e:
            db.session.rollback()
            logger.error(f'Integrity error updating contract {contract_id}: {str(e)}')
            return jsonify({'message': 'Xung đột khi cập nhật hợp đồng, vui lòng thử lại'}), 409
        except SQLAlchemyError as db_error:
            db.session.rollback()
            logger.error(f'Database error committing contract {contract_id}: {str(db_error)}')
            return jsonify({'message': 'Lỗi cơ sở dữ liệu khi lưu hợp đồng', 'error': str(db_error)}), 500

        try:
            contract_data = contract.to_dict()
            logger.debug(f'Contract data before jsonify: {contract_data}')
        except Exception as dict_error:
            logger.error(f'Failed to serialize contract {contract_id}: {str(dict_error)}')
            return jsonify({'message': 'Lỗi khi lấy dữ liệu hợp đồng', 'error': str(dict_error)}), 500

        try:
            response = jsonify(contract_data)
            response.json_encoder = CustomJSONEncoder
        except Exception as json_error:
            logger.error(f'Failed to jsonify contract data for {contract_id}: {str(json_error)}')
            return jsonify({'message': 'Lỗi khi trả về dữ liệu hợp đồng', 'error': str(json_error)}), 500

        return response, 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Unexpected error in update_contract for contract {contract_id}: {str(e)}')
        return jsonify({'message': 'Lỗi server khi cập nhật hợp đồng', 'error': str(e)}), 500

@contract_bp.route('/admin/contracts/<int:contract_id>', methods=['DELETE'])
@admin_required()
def delete_contract(contract_id):
    try:
        contract = Contract.query.get(contract_id)
        if not contract:
            return jsonify({'message': 'Không tìm thấy hợp đồng'}), 404

        if contract.status == 'ACTIVE':
            return jsonify({'message': 'Không thể xóa hợp đồng đang ACTIVE'}), 400

        room_id = contract.room_id
        db.session.delete(contract)

        room = Room.query.with_for_update().get(room_id)
        if contract.status == 'ACTIVE':
            room.current_person_number = max(0, room.current_person_number - 1)
            room.status = 'OCCUPIED' if room.current_person_number >= room.capacity else 'AVAILABLE'
            logger.debug(f'Updated current_person_number for room {room_id}: {room.current_person_number}')

        try:
            db.session.commit()
            logger.info(f'Contract {contract_id} deleted')
        except IntegrityError:
            db.session.rollback()
            logger.error(f'Failed to delete contract {contract_id}')
            return jsonify({'message': 'Xung đột khi xóa hợp đồng, vui lòng thử lại'}), 409

        return '', 204
    except Exception as e:
        db.session.rollback()
        logger.error(f'Error in delete_contract: {str(e)}')
        return jsonify({'message': 'Lỗi server khi xóa hợp đồng'}), 500

@contract_bp.route('/me/contracts', methods=['GET'])
@user_required()
def get_user_contracts():
    try:
        identity = get_jwt_identity()
        claims = get_jwt()
        if not identity:
            logger.error('No JWT identity found')
            return jsonify({'message': 'Token không hợp lệ hoặc thiếu thông tin'}), 401

        if isinstance(identity, str):
            try:
                identity_dict = {
                    'id': int(identity),
                    'type': claims.get('type', 'USER')
                }
            except ValueError:
                logger.error(f'Invalid identity format, cannot convert to int: {identity}')
                return jsonify({'message': 'Token sai định dạng'}), 401
        else:
            logger.error(f'JWT identity is not a string: {identity}')
            return jsonify({'message': 'Token sai định dạng'}), 401

        if identity_dict['type'] not in ['USER']:
            logger.error(f'Invalid type in identity: {identity_dict}')
            return jsonify({'message': 'Token chứa type không hợp lệ'}), 401

        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)

        contracts = Contract.query.filter_by(user_id=identity_dict['id']).paginate(page=page, per_page=limit)

        try:
            contract_data = [contract.to_dict() for contract in contracts.items]
            logger.debug(f'Contract data before jsonify: {contract_data}')
        except Exception as dict_error:
            logger.error(f'Failed to serialize contracts for user {identity_dict["id"]}: {str(dict_error)}')
            return jsonify({'message': 'Lỗi khi lấy dữ liệu hợp đồng', 'error': str(dict_error)}), 500

        logger.info(f'Retrieved {contracts.total} contracts for user {identity_dict["id"]}')
        return jsonify({
            'contracts': contract_data,
            'total': contracts.total,
            'pages': contracts.pages,
            'current_page': contracts.page
        }), 200
    except Exception as e:
        logger.error(f'Unexpected error in get_user_contracts for user: {str(e)}')
        return jsonify({'message': 'Lỗi server khi lấy danh sách hợp đồng của người dùng', 'error': str(e)}), 500

@contract_bp.route('/admin/update-contract-status', methods=['POST'])
@admin_required()
def manual_update_contract_status():
    try:
        update_contract_status()
        return jsonify({'message': 'Cập nhật trạng thái hợp đồng thành công'}), 200
    except Exception as e:
        logger.error(f'Error in manual_update_contract_status: {str(e)}')
        return jsonify({'message': 'Lỗi khi cập nhật trạng thái hợp đồng', 'error': str(e)}), 500