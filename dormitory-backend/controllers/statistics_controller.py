from flask import Blueprint, jsonify, request
from extensions import db
from sqlalchemy import func, extract, and_, or_
from datetime import datetime
import pendulum
from models.service import Service
from models.service_rate import ServiceRate
from models.bill_detail import BillDetail
from models.contract import Contract
from models.room import Room
from models.area import Area
from models.user import User
from models.report import Report
from models.report_type import ReportType
from models.room_status_history import RoomStatusHistory
from models.user_room_history import UserRoomHistory
from controllers.auth_controller import admin_required
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

statistics_bp = Blueprint('statistics', __name__)

def snapshot_room_status(year, month, room_id=None):
    """Snapshot room status for non-deleted rooms or a specific non-deleted room for a given year and month."""
    try:
        logger.info(f"Starting room status snapshot for {year}-{month}, room_id={room_id}, excluding soft-deleted rooms")
        query = Room.query.filter_by(is_deleted=False)
        if room_id:
            query = query.filter_by(room_id=room_id)
        rooms = query.all()
        
        current_time = datetime.utcnow()
        for room in rooms:
            existing = RoomStatusHistory.query.filter_by(room_id=room.room_id, year=year, month=month).first()
            if existing:
                existing.status = room.status
                existing.updated_at = current_time
                logger.debug(f"Updated RoomStatusHistory for room_id={room.room_id}, year={year}, month={month}, status={room.status}")
            else:
                snapshot = RoomStatusHistory(
                    area_id=room.area_id,
                    room_id=room.room_id,
                    room_name=room.name,
                    year=year,
                    month=month,
                    status=room.status,
                    created_at=current_time,
                    updated_at=current_time
                )
                db.session.add(snapshot)
                logger.debug(f"Created RoomStatusHistory for room_id={room.room_id}, year={year}, month={month}, status={room.status}")
        db.session.commit()
        logger.info(f"Completed room status snapshot for {year}-{month}")
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to save room status snapshot for {year}-{month}: {str(e)}")
        return False

def save_user_room_snapshot(year, month, room_id=None):
    """Snapshot user count for non-deleted rooms or a specific non-deleted room, excluding soft-deleted rooms."""
    try:
        logger.info(f"Starting user room snapshot for {year}-{month}, room_id={room_id}, excluding soft-deleted rooms")
        query = Room.query.filter_by(is_deleted=False)
        if room_id:
            query = query.filter_by(room_id=room_id)
        rooms = query.all()
        current_time = datetime.utcnow()
        for room in rooms:
            existing = UserRoomHistory.query.filter_by(room_id=room.room_id, year=year, month=month).first()
            user_count = Contract.query.filter_by(room_id=room.room_id, status='ACTIVE', is_deleted=False).count()
            if existing:
                existing.user_count = user_count
                existing.updated_at = current_time
                logger.debug(f"Updated UserRoomHistory for room_id={room.room_id}, year={year}, month={month}, user_count={user_count}")
            else:
                snapshot = UserRoomHistory(
                    area_id=room.area_id,
                    room_id=room.room_id,
                    room_name=room.name,
                    year=year,
                    month=month,
                    user_count=user_count,
                    created_at=current_time,
                    updated_at=current_time
                )
                db.session.add(snapshot)
                logger.debug(f"Created UserRoomHistory for room_id={room.room_id}, year={year}, month={month}, user_count={user_count}")
        db.session.commit()
        logger.info(f"Completed user room snapshot for {year}-{month}")
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to save user room snapshot for {year}-{month}, room_id={room_id}: {str(e)}")
        return False

@statistics_bp.route('/api/statistics/consumption', methods=['GET'])
@admin_required()
def get_monthly_consumption():
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        area_id = request.args.get('area_id', type=int)

        if area_id is not None:
            query = (
                db.session.query(
                    Area.area_id,
                    Area.name.label('area_name'),
                    Service.service_id,
                    Service.name.label('service_name'),
                    Service.unit.label('service_unit'),
                    func.sum(BillDetail.current_reading - BillDetail.previous_reading).label('total_consumption'),
                    extract('month', BillDetail.bill_month).label('month')
                )
                .select_from(Area)
                .join(Room, Room.area_id == Area.area_id)
                .join(Contract, Contract.room_id == Room.room_id)
                .join(User, User.user_id == Contract.user_id)
                .join(BillDetail, BillDetail.room_id == Room.room_id)
                .join(ServiceRate, ServiceRate.rate_id == BillDetail.rate_id)
                .join(Service, Service.service_id == ServiceRate.service_id)
                .filter(
                    Room.is_deleted == False,
                    Contract.is_deleted == False,
                    User.is_deleted == False
                )
            )
            query = query.filter(Area.area_id == area_id)
            if year:
                query = query.filter(extract('year', BillDetail.bill_month) == year)
            if month:
                query = query.filter(extract('month', BillDetail.bill_month) == month)
            query = query.group_by(
                Area.area_id,
                Area.name,
                Service.service_id,
                Service.name,
                Service.unit,
                extract('month', BillDetail.bill_month)
            )
        else:
            query = (
                db.session.query(
                    Service.service_id,
                    Service.name.label('service_name'),
                    Service.unit.label('service_unit'),
                    func.sum(BillDetail.current_reading - BillDetail.previous_reading).label('total_consumption'),
                    extract('month', BillDetail.bill_month).label('month')
                )
                .select_from(BillDetail)
                .join(Room, Room.room_id == BillDetail.room_id)
                .join(Contract, Contract.room_id == Room.room_id)
                .join(User, User.user_id == Contract.user_id)
                .join(ServiceRate, ServiceRate.rate_id == BillDetail.rate_id)
                .join(Service, Service.service_id == ServiceRate.service_id)
                .filter(
                    Room.is_deleted == False,
                    Contract.is_deleted == False,
                    User.is_deleted == False
                )
            )
            if year:
                query = query.filter(extract('year', BillDetail.bill_month) == year)
            if month:
                query = query.filter(extract('month', BillDetail.bill_month) == month)
            query = query.group_by(
                Service.service_id,
                Service.name,
                Service.unit,
                extract('month', BillDetail.bill_month)
            )

        results = query.all()

        response = {}
        if area_id is not None:
            for row in results:
                area_id = row.area_id
                area_name = row.area_name
                service_name = row.service_name
                service_unit = row.service_unit
                month = int(row.month)
                total_consumption = float(row.total_consumption)
                if area_id not in response:
                    response[area_id] = {
                        'area_id': area_id,
                        'area_name': area_name,
                        'service_units': {},
                        'months': {}
                    }
                response[area_id]['service_units'][service_name] = service_unit
                if month not in response[area_id]['months']:
                    response[area_id]['months'][month] = {}
                response[area_id]['months'][month][service_name] = total_consumption
        else:
            total_area_id = 0
            response[total_area_id] = {
                'area_id': total_area_id,
                'area_name': 'Toàn khu kí túc xá',
                'service_units': {},
                'months': {}
            }
            for row in results:
                service_name = row.service_name
                service_unit = row.service_unit
                month = int(row.month)
                total_consumption = float(row.total_consumption)
                response[total_area_id]['service_units'][service_name] = service_unit
                if month not in response[total_area_id]['months']:
                    response[total_area_id]['months'][month] = {}
                response[total_area_id]['months'][month][service_name] = total_consumption

        formatted_response = list(response.values())
        return jsonify({
            'status': 'success',
            'data': formatted_response
        }), 200
    except Exception as e:
        logger.error(f"Error in get_monthly_consumption: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Lỗi xử lý dữ liệu: {str(e)}'
        }), 500

@statistics_bp.route('/api/statistics/rooms/status', methods=['GET'])
@admin_required()
def get_room_status_stats():
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        area_id = request.args.get('area_id', type=int)
        room_id = request.args.get('room_id', type=int)

        if year:
            if month:
                query = RoomStatusHistory.query.filter_by(year=year, month=month)
                if area_id:
                    query = query.filter_by(area_id=area_id)
                if room_id:
                    query = query.filter_by(room_id=room_id)
                results = query.all()
                if room_id:
                    response = [row.to_dict() for row in results]
                else:
                    response = {}
                    for row in results:
                        area_id = row.area_id
                        if area_id not in response:
                            response[area_id] = {
                                'area_id': area_id,
                                'area_name': row.area_name,
                                'rooms': {}
                            }
                        response[area_id]['rooms'][row.room_id] = {
                            'room_name': row.room_name,
                            'status': row.status,
                            'month': row.month
                        }
                    response = list(response.values())
            else:
                query = (
                    db.session.query(
                        Area.area_id,
                        Area.name.label('area_name'),
                        RoomStatusHistory.room_id,
                        RoomStatusHistory.room_name,
                        RoomStatusHistory.status,
                        RoomStatusHistory.month
                    )
                    .join(Area, Area.area_id == RoomStatusHistory.area_id)
                    .filter(RoomStatusHistory.year == year)
                )
                if area_id:
                    query = query.filter(RoomStatusHistory.area_id == area_id)
                if room_id:
                    query = query.filter(RoomStatusHistory.room_id == room_id)
                results = query.order_by(RoomStatusHistory.room_id, RoomStatusHistory.month).all()
                response = {}
                for row in results:
                    area_id = row.area_id
                    if area_id not in response:
                        response[area_id] = {
                            'area_id': area_id,
                            'area_name': row.area_name,
                            'rooms': {}
                        }
                    if row.room_id not in response[area_id]['rooms']:
                        response[area_id]['rooms'][row.room_id] = {
                            'room_name': row.room_name,
                            'monthly_status': {m: None for m in range(1, 13)}
                        }
                    response[area_id]['rooms'][row.room_id]['monthly_status'][row.month] = row.status
                formatted_response = []
                for area_data in response.values():
                    area_rooms = []
                    for room_id, room_data in area_data['rooms'].items():
                        monthly_status = [
                            {'month': m, 'status': room_data['monthly_status'][m]}
                            for m in range(1, 13)
                        ]
                        area_rooms.append({
                            'room_id': room_id,
                            'room_name': room_data['room_name'],
                            'monthly_status': monthly_status
                        })
                    formatted_response.append({
                        'area_id': area_data['area_id'],
                        'area_name': area_data['area_name'],
                        'rooms': area_rooms
                    })
                response = formatted_response
        else:
            current_time = pendulum.now('Asia/Ho_Chi_Minh')
            query_month = month if month else current_time.month
            query = (
                db.session.query(
                    Area.area_id,
                    Area.name.label('area_name'),
                    Room.room_id,
                    Room.name.label('room_name'),
                    Room.status,
                    func.lit(query_month).label('month')
                )
                .join(Area, Area.area_id == Room.area_id)
                .filter(Room.is_deleted == False)
            )
            if area_id:
                query = query.filter(Area.area_id == area_id)
            if room_id:
                query = query.filter(Room.room_id == room_id)
            results = query.all()
            if room_id:
                response = [
                    {
                        'area_id': row.area_id,
                        'area_name': row.area_name,
                        'room_id': row.room_id,
                        'room_name': row.room_name,
                        'status': row.status,
                        'month': row.month
                    } for row in results
                ]
            else:
                response = {}
                for row in results:
                    area_id = row.area_id
                    if area_id not in response:
                        response[area_id] = {
                            'area_id': area_id,
                            'area_name': row.area_name,
                            'rooms': {}
                        }
                    response[area_id]['rooms'][row.room_id] = {
                        'room_name': row.room_name,
                        'status': row.status,
                        'month': row.month
                    }
                response = list(response.values())
        return jsonify({
            'status': 'success',
            'data': response
        }), 200
    except Exception as e:
        logger.error(f"Error in get_room_status_stats: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@statistics_bp.route('/api/statistics/rooms/capacity', methods=['GET'])
@admin_required()
def get_room_capacity_stats():
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        quarter = request.args.get('quarter', type=int)
        area_id = request.args.get('area_id', type=int)
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                Room.capacity,
                func.count(Room.room_id).label('room_count')
            )
            .join(Area, Area.area_id == Room.area_id)
            .join(Contract, Contract.room_id == Room.room_id, isouter=True)
            .filter(
                Room.status == 'OCCUPIED',
                Room.is_deleted == False,
                Contract.is_deleted == False,
                Contract.status == 'ACTIVE'
            )
        )
        if area_id:
            query = query.filter(Area.area_id == area_id)
        if year:
            query = query.filter(extract('year', Contract.start_date) <= year, extract('year', Contract.end_date) >= year)
        if month:
            query = query.filter(extract('month', Contract.start_date) <= month, extract('month', Contract.end_date) >= month)
        if quarter:
            query = query.filter(
                (extract('month', Contract.start_date) <= (quarter * 3), extract('month', Contract.end_date) >= ((quarter - 1) * 3 + 1))
            )
        query = query.group_by(Area.area_id, Area.name, Room.capacity)
        results = query.all()
        response = {}
        for row in results:
            area_id = row.area_id
            area_name = row.area_name
            capacity = row.capacity
            room_count = row.room_count
            if area_id not in response:
                response[area_id] = {
                    'area_id': area_id,
                    'area_name': area_name,
                    'capacity_counts': {}
                }
            response[area_id]['capacity_counts'][str(capacity)] = room_count
        formatted_response = list(response.values())
        return jsonify({
            'status': 'success',
            'data': formatted_response
        }), 200
    except Exception as e:
        logger.error(f"Error in get_room_capacity_stats: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@statistics_bp.route('/api/statistics/contracts', methods=['GET'])
@admin_required()
def get_contract_stats():
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        quarter = request.args.get('quarter', type=int)
        area_id = request.args.get('area_id', type=int)
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                func.count(Contract.contract_id).label('contract_count'),
                extract('month', Contract.start_date).label('month')
            )
            .join(Room, Room.room_id == Contract.room_id)
            .join(Area, Area.area_id == Room.area_id)
            .filter(
                Room.is_deleted == False,
                Contract.is_deleted == False,
                Contract.status == 'ACTIVE'
            )
        )
        if area_id:
            query = query.filter(Area.area_id == area_id)
        if year:
            query = query.filter(extract('year', Contract.start_date) <= year, extract('year', Contract.end_date) >= year)
        if month:
            query = query.filter(extract('month', Contract.start_date) <= month, extract('month', Contract.end_date) >= month)
        if quarter:
            query = query.filter(
                (extract('month', Contract.start_date) <= (quarter * 3), extract('month', Contract.end_date) >= ((quarter - 1) * 3 + 1))
            )
        query = query.group_by(Area.area_id, Area.name, extract('month', Contract.start_date))
        results = query.all()
        response = {}
        for row in results:
            area_id = row.area_id
            area_name = row.area_name
            month = int(row.month) if row.month else None
            contract_count = row.contract_count
            if area_id not in response:
                response[area_id] = {
                    'area_id': area_id,
                    'area_name': area_name,
                    'months': {}
                }
            if month:
                response[area_id]['months'][month] = contract_count
        formatted_response = list(response.values())
        return jsonify({
            'status': 'success',
            'data': formatted_response
        }), 200
    except Exception as e:
        logger.error(f"Error in get_contract_stats: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@statistics_bp.route('/api/statistics/users', methods=['GET'])
@admin_required()
def get_user_stats():
    try:
        area_id = request.args.get('area_id', type=int)
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                func.count(User.user_id).label('user_count')
            )
            .outerjoin(Contract, Contract.user_id == User.user_id)
            .outerjoin(Room, Room.room_id == Contract.room_id)
            .outerjoin(Area, Area.area_id == Room.area_id)
            .filter(
                User.is_deleted == False,
                Room.is_deleted == False,
                Contract.is_deleted == False
            )
        )
        if area_id:
            query = query.filter(Area.area_id == area_id)
        query = query.group_by(Area.area_id, Area.name)
        results = query.all()
        response = [
            {
                'area_id': row.area_id,
                'area_name': row.area_name,
                'user_count': row.user_count
            } for row in results
        ]
        return jsonify({'status': 'success', 'data': response}), 200
    except Exception as e:
        logger.error(f"Error in get_user_stats: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@statistics_bp.route('/api/statistics/users/monthly', methods=['GET'])
@admin_required()
def get_user_monthly_stats():
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        area_id = request.args.get('area_id', type=int)
        room_id = request.args.get('room_id', type=int)
        if year:
            if month:
                query = UserRoomHistory.query.filter_by(year=year, month=month)
                if area_id:
                    query = query.filter_by(area_id=area_id)
                if room_id:
                    query = query.filter_by(room_id=room_id)
                results = query.all()
                if room_id:
                    response = [row.to_dict() for row in results]
                else:
                    response = {}
                    for row in results:
                        area_id = row.area_id
                        if area_id not in response:
                            response[area_id] = {
                                'area_id': area_id,
                                'area_name': row.area_name,
                                'months': {},
                                'total_users': 0
                            }
                        response[area_id]['months'][row.month] = response[area_id]['months'].get(row.month, 0) + row.user_count
                        response[area_id]['total_users'] += row.user_count
                    response = list(response.values())
            else:
                query = (
                    db.session.query(
                        Area.area_id,
                        Area.name.label('area_name'),
                        UserRoomHistory.month,
                        func.sum(UserRoomHistory.user_count).label('total_users')
                    )
                    .join(Area, Area.area_id == UserRoomHistory.area_id)
                    .filter(UserRoomHistory.year == year)
                )
                if area_id:
                    query = query.filter(UserRoomHistory.area_id == area_id)
                if room_id:
                    query = query.filter(UserRoomHistory.room_id == room_id)
                query = query.group_by(Area.area_id, Area.name, UserRoomHistory.month)
                results = query.all()
                response = {}
                for row in results:
                    area_id = row.area_id
                    if area_id not in response:
                        response[area_id] = {
                            'area_id': area_id,
                            'area_name': row.area_name,
                            'months': {},
                            'total_users': 0
                        }
                    response[area_id]['months'][row.month] = row.total_users
                    response[area_id]['total_users'] += row.total_users
                response = list(response.values())
                for area_data in response:
                    for m in range(1, 13):
                        if m not in area_data['months']:
                            area_data['months'][m] = 0
        else:
            current_time = pendulum.now('Asia/Ho_Chi_Minh')
            query_year = current_time.year
            query_month = month if month else current_time.month
            query = (
                db.session.query(
                    Area.area_id,
                    Area.name.label('area_name'),
                    func.count(Contract.contract_id).label('user_count'),
                    func.lit(query_month).label('month')
                )
                .select_from(Room)
                .join(Area, Area.area_id == Room.area_id)
                .outerjoin(Contract, and_(
                    Contract.room_id == Room.room_id,
                    Contract.is_deleted == False,
                    Contract.status == 'ACTIVE',
                    extract('year', Contract.start_date) <= query_year,
                    extract('year', Contract.end_date) >= query_year,
                    extract('month', Contract.start_date) <= query_month,
                    extract('month', Contract.end_date) >= query_month
                ))
                .filter(Room.is_deleted == False)
            )
            if area_id:
                query = query.filter(Area.area_id == area_id)
            if room_id:
                query = query.filter(Room.room_id == room_id)
            results = query.all()
            response = {}
            for row in results:
                area_id = row[0]
                if area_id not in response:
                    response[area_id] = {
                        'area_id': area_id,
                        'area_name': row[1],
                        'months': {},
                        'total_users': 0
                    }
                response[area_id]['months'][int(row[3])] = row[2]
                response[area_id]['total_users'] += row[2]
            response = list(response.values())
            for area_data in response:
                for m in range(1, 13):
                    if m not in area_data['months']:
                        area_data['months'][m] = 0
        return jsonify({
            'status': 'success',
            'data': response
        }), 200
    except Exception as e:
        logger.error(f"Error in get_user_monthly_stats: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Lỗi xử lý dữ liệu: {str(e)}'
        }), 500

@statistics_bp.route('/api/statistics/rooms/occupancy-rate', methods=['GET'])
@admin_required()
def get_occupancy_rate_stats():
    try:
        area_id = request.args.get('area_id', type=int)
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                func.count(Room.room_id).label('total_rooms'),
                func.sum(db.case((Room.status == 'OCCUPIED', 1), else_=0)).label('occupied_rooms')
            )
            .join(Area, Area.area_id == Room.area_id)
            .filter(Room.is_deleted == False)
        )
        if area_id:
            query = query.filter(Area.area_id == area_id)
        query = query.group_by(Area.area_id, Area.name)
        results = query.all()
        response = []
        for row in results:
            total_rooms = row.total_rooms
            occupied_rooms = row.occupied_rooms
            occupancy_rate = (occupied_rooms / total_rooms * 100) if total_rooms > 0 else 0
            response.append({
                'area_id': row.area_id,
                'area_name': row.area_name,
                'total_rooms': total_rooms,
                'occupied_rooms': occupied_rooms,
                'occupancy_rate': round(occupancy_rate, 2)
            })
        return jsonify({
            'status': 'success',
            'data': response
        }), 200
    except Exception as e:
        logger.error(f"ожалуй: Error in get_occupancy_rate_stats: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@statistics_bp.route('/api/statistics/reports', methods=['GET'])
@admin_required()
def get_report_stats():
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        area_id = request.args.get('area_id', type=int)
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                ReportType.report_type_id,
                ReportType.name.label('report_type_name'),
                func.count(Report.report_id).label('report_count'),
                extract('month', Report.created_at).label('month'),
                extract('year', Report.created_at).label('year')
            )
            .join(Room, Room.room_id == Report.room_id)
            .join(Area, Area.area_id == Room.area_id)
            .join(ReportType, ReportType.report_type_id == Report.report_type_id)
            .filter(
                Room.is_deleted == False,
                Report.created_at.isnot(None)
            )
        )
        if area_id:
            query = query.filter(Area.area_id == area_id)
        if year:
            query = query.filter(extract('year', Report.created_at) == year)
        if month:
            query = query.filter(extract('month', Report.created_at) == month)
        query = query.group_by(
            Area.area_id,
            Area.name,
            ReportType.report_type_id,
            ReportType.name,
            extract('month', Report.created_at),
            extract('year', Report.created_at)
        )
        results = query.all()
        response = {}
        for row in results:
            area_id = row.area_id
            area_name = row.area_name
            report_type_id = row.report_type_id
            report_type_name = row.report_type_name
            report_count = row.report_count
            month = int(row.month) if row.month else None
            year = int(row.year) if row.year else None
            if area_id not in response:
                response[area_id] = {
                    'area_id': area_id,
                    'area_name': area_name,
                    'years': {},
                    'report_types': {}
                }
            response[area_id]['report_types'][str(report_type_id)] = report_type_name
            if year not in response[area_id]['years']:
                response[area_id]['years'][year] = {'total': 0, 'months': {}, 'types': {}}
            response[area_id]['years'][year]['total'] += report_count
            if month:
                if month not in response[area_id]['years'][year]['months']:
                    response[area_id]['years'][year]['months'][month] = {}
                response[area_id]['years'][year]['months'][month][report_type_name] = report_count
            if report_type_name not in response[area_id]['years'][year]['types']:
                response[area_id]['years'][year]['types'][report_type_name] = 0
            response[area_id]['years'][year]['types'][report_type_name] += report_count
        formatted_response = list(response.values())
        trend_stats = []
        for area_data in formatted_response:
            area_id = area_data['area_id']
            area_name = area_data['area_name']
            for year, year_data in area_data['years'].items():
                contract_query = (
                    db.session.query(
                        func.count(Contract.contract_id).label('contract_count')
                    )
                    .join(Room, Room.room_id == Contract.room_id)
                    .join(Area, Area.area_id == Room.area_id)
                    .filter(
                        Area.area_id == area_id,
                        Room.is_deleted == False,
                        Contract.is_deleted == False,
                        Contract.status == 'ACTIVE',
                        extract('year', Contract.start_date) <= year,
                        extract('year', Contract.end_date) >= year
                    )
                )
                contract_result = contract_query.one()
                contract_count = contract_result.contract_count
                report_per_contract = (year_data['total'] / contract_count) if contract_count > 0 else 0
                trend_stats.append({
                    'area_id': area_id,
                    'area_name': area_name,
                    'year': year,
                    'total_reports': year_data['total'],
                    'total_contracts': contract_count,
                    'report_per_contract': round(report_per_contract, 2)
                })
        return jsonify({
            'status': 'success',
            'data': formatted_response,
            'trends': trend_stats
        }), 200
    except Exception as e:
        logger.error(f"Error in get_report_stats: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@statistics_bp.route('/admin/save-snapshots', methods=['POST'])
@admin_required()
def save_snapshots():
    try:
        year = request.json.get('year', type=int)
        month = request.json.get('month', type=int)
        current_time = pendulum.now('Asia/Ho_Chi_Minh')
        year = year or current_time.year
        month = month or current_time.month
        if not (1 <= month <= 12):
            return jsonify({'status': 'error', 'message': 'Invalid month'}), 400
        if year < 2000 or year > current_time.year:
            return jsonify({'status': 'error', 'message': 'Invalid year'}), 400
        success_room = snapshot_room_status(year=year, month=month)
        success_user = save_user_room_snapshot(year=year, month=month)
        if success_room and success_user:
            return jsonify({
                'status': 'success',
                'message': f'Lưu snapshot thành công cho {year}-{month}'
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': f'Lưu snapshot thất bại cho {year}-{month}'
            }), 500
    except Exception as e:
        logger.error(f"Error saving snapshots: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Lỗi khi lưu snapshot: {str(e)}'
        }), 500

@statistics_bp.route('/api/statistics/rooms/status/summary', methods=['GET'])
@admin_required()
def get_room_status_summary():
    try:
        year = request.args.get('year', type=int)
        area_id = request.args.get('area_id', type=int)
        
        if not year:
            return jsonify({
                'status': 'error',
                'message': 'Year is required'
            }), 400

        logger.info(f"Fetching room status summary for year={year}, area_id={area_id}")

        query = (
            db.session.query(
                RoomStatusHistory.month,
                RoomStatusHistory.status,
                func.count().label('count')
            )
            .filter(RoomStatusHistory.year == year)
            .group_by(RoomStatusHistory.month, RoomStatusHistory.status)
        )

        if area_id:
            query = query.filter(RoomStatusHistory.area_id == area_id)

        results = query.order_by(RoomStatusHistory.month).all()

        response = []
        for month in range(1, 13):
            month_data = {
                'month': month,
                'statuses': {}
            }
            month_results = [r for r in results if r.month == month]
            for result in month_results:
                month_data['statuses'][result.status] = result.count
            for status in ['AVAILABLE', 'OCCUPIED', 'MAINTENANCE', 'DISABLED']:
                if status not in month_data['statuses']:
                    month_data['statuses'][status] = 0
            response.append(month_data)

        return jsonify({
            'status': 'success',
            'data': response
        }), 200
    except Exception as e:
        logger.error(f"Error in get_room_status_summary: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error processing data: {str(e)}'
        }), 500

@statistics_bp.route('/api/statistics/users/summary', methods=['GET'])
@admin_required()
def get_user_summary():
    try:
        year = request.args.get('year', type=int)
        area_id = request.args.get('area_id', type=int)
        
        if not year:
            logger.error("Year parameter is required but not provided")
            return jsonify({
                'status': 'error',
                'message': 'Year is required'
            }), 400

        logger.info(f"Fetching user summary for year={year}, area_id={area_id}")

        # Validate area_id if provided, without is_deleted filter
        if area_id:
            area_exists = Area.query.filter_by(area_id=area_id).first()
            if not area_exists:
                logger.error(f"Invalid area_id={area_id}: Area does not exist")
                return jsonify({
                    'status': 'error',
                    'message': f'Invalid area_id: {area_id}'
                }), 400

        query = (
            db.session.query(
                UserRoomHistory.month,
                func.sum(UserRoomHistory.user_count).label('total_users')
            )
            .filter(UserRoomHistory.year == year)
            .group_by(UserRoomHistory.month)
        )

        if area_id:
            query = query.filter(UserRoomHistory.area_id == area_id)

        results = query.order_by(UserRoomHistory.month).all()

        response = []
        for month in range(1, 13):
            month_data = {
                'month': month,
                'total_users': 0
            }
            month_result = next((r for r in results if r.month == month), None)
            if month_result:
                # Ensure total_users is an integer
                total_users = int(month_result.total_users) if month_result.total_users is not None else 0
                month_data['total_users'] = total_users
            response.append(month_data)

        logger.debug(f"User summary response: {response}")

        return jsonify({
            'status': 'success',
            'data': response
        }), 200
    except Exception as e:
        logger.error(f"Error in get_user_summary for year={year}, area_id={area_id}: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Error processing data: {str(e)}'
        }), 500
    
@statistics_bp.route('/api/statistics/snapshot', methods=['POST'])
@admin_required()
def manual_snapshot():
    """Manually trigger snapshots for room status and user counts for all non-deleted rooms using current time."""
    try:
        current_time = pendulum.now('Asia/Ho_Chi_Minh')
        year = current_time.year
        month = current_time.month
        
        logger.info(f"Manual snapshot triggered for all non-deleted rooms, {year}-{month}")
        
        success_room = snapshot_room_status(year=year, month=month)
        success_user = save_user_room_snapshot(year=year, month=month)
        
        if success_room and success_user:
            return jsonify({
                'status': 'success',
                'message': f'Manually triggered snapshots successfully for all non-deleted rooms, {year}-{month}'
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': f'Failed to trigger snapshots for all non-deleted rooms, {year}-{month}'
            }), 500
    except Exception as e:
        logger.error(f"Error in manual_snapshot for all non-deleted rooms, {year}-{month}: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error triggering snapshots: {str(e)}'
        }), 500

@statistics_bp.route('/api/statistics/rooms/fill-rate', methods=['GET'])
@admin_required()
def get_room_fill_rate_stats():
    """Get fill rate statistics for rooms, including capacity, current occupants, and fill rate per room and area."""
    try:
        area_id = request.args.get('area_id', type=int)
        room_id = request.args.get('room_id', type=int)

        logger.info(f"Fetching room fill rate stats, area_id={area_id}, room_id={room_id}")

        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                Room.room_id,
                Room.name.label('room_name'),
                Room.capacity,
                Room.current_person_number
            )
            .join(Area, Area.area_id == Room.area_id)
            .filter(Room.is_deleted == False)
        )

        if area_id:
            query = query.filter(Area.area_id == area_id)
        if room_id:
            query = query.filter(Room.room_id == room_id)

        results = query.all()

        if room_id:
            response = [
                {
                    'area_id': row.area_id,
                    'area_name': row.area_name,
                    'room_id': row.room_id,
                    'room_name': row.room_name,
                    'capacity': row.capacity,
                    'current_person_number': row.current_person_number,
                    'fill_rate': round((row.current_person_number / row.capacity * 100), 2) if row.capacity > 0 else 0
                } for row in results
            ]
        else:
            response = {}
            total_capacity = {}
            total_users = {}

            for row in results:
                area_id = row.area_id
                if area_id not in response:
                    response[area_id] = {
                        'area_id': area_id,
                        'area_name': row.area_name,
                        'total_capacity': 0,
                        'total_users': 0,
                        'area_fill_rate': 0,
                        'rooms': {}
                    }
                    total_capacity[area_id] = 0
                    total_users[area_id] = 0

                response[area_id]['rooms'][row.room_id] = {
                    'room_name': row.room_name,
                    'capacity': row.capacity,
                    'current_person_number': row.current_person_number,
                    'fill_rate': round((row.current_person_number / row.capacity * 100), 2) if row.capacity > 0 else 0
                }
                total_capacity[area_id] += row.capacity
                total_users[area_id] += row.current_person_number

            for area_id in response:
                response[area_id]['total_capacity'] = total_capacity[area_id]
                response[area_id]['total_users'] = total_users[area_id]
                response[area_id]['area_fill_rate'] = round((total_users[area_id] / total_capacity[area_id] * 100), 2) if total_capacity[area_id] > 0 else 0

            response = list(response.values())

        return jsonify({
            'status': 'success',
            'data': response
        }), 200
    except Exception as e:
        logger.error(f"Error in get_room_fill_rate_stats: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error processing data: {str(e)}'
        }), 500