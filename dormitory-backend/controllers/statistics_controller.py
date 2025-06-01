# backend/controllers/statistics_controller.py
from flask import Blueprint, jsonify, request
from extensions import db
from sqlalchemy import func, extract, and_, or_
from datetime import datetime, timedelta
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

def save_user_room_snapshot(target_year=None, target_month=None):
    try:
        current_time = datetime.utcnow()
        is_current_month = False
        if target_year and target_month:
            year = target_year
            month = target_month
            # Check if target is current month
            if year == current_time.year and month == current_time.month:
                is_current_month = True
        else:
            # Default to current month for real-time updates
            year = current_time.year
            month = current_time.month
            is_current_month = True

        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                Room.room_id,
                Room.name.label('room_name'),
                func.count(Contract.contract_id).label('user_count')
            )
            .join(Room, Room.room_id == Contract.room_id)
            .join(Area, Area.area_id == Room.area_id)
            .filter(
                Contract.is_deleted == False,
                Contract.status == 'ACTIVE',
                extract('year', Contract.start_date) <= year,
                extract('year', Contract.end_date) >= year,
                extract('month', Contract.start_date) <= month,
                extract('month', Contract.end_date) >= month
            )
            .group_by(Area.area_id, Area.name, Room.room_id, Room.name)
        )

        results = query.all()

        for row in results:
            existing = UserRoomHistory.query.filter_by(
                room_id=row.room_id, year=year, month=month
            ).first()
            if existing:
                if is_current_month:
                    # Update existing record for current month
                    existing.user_count = row.user_count
                    existing.updated_at = current_time
                    logger.info(f"Updated user room snapshot for room_id={row.room_id}, year={year}, month={month}")
                else:
                    logger.warning(f"User room snapshot already exists for room_id={row.room_id}, year={year}, month={month}")
                    continue
            else:
                # Insert new record
                history = UserRoomHistory(
                    area_id=row.area_id,
                    room_id=row.room_id,
                    room_name=row.room_name,
                    year=year,
                    month=month,
                    user_count=row.user_count,
                    created_at=current_time,
                    updated_at=current_time
                )
                db.session.add(history)

        # Handle empty rooms
        empty_rooms = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                Room.room_id,
                Room.name.label('room_name')
            )
            .join(Area, Area.area_id == Room.area_id)
            .filter(
                Room.is_deleted == False,
                ~Room.room_id.in_(
                    db.session.query(Contract.room_id)
                    .filter(
                        Contract.is_deleted == False,
                        Contract.status == 'ACTIVE',
                        extract('year', Contract.start_date) <= year,
                        extract('year', Contract.end_date) >= year,
                        extract('month', Contract.start_date) <= month,
                        extract('month', Contract.end_date) >= month
                    )
                )
            )
        ).all()

        for row in empty_rooms:
            existing = UserRoomHistory.query.filter_by(
                room_id=row.room_id, year=year, month=month
            ).first()
            if existing:
                if is_current_month:
                    existing.user_count = 0
                    existing.updated_at = current_time
                    logger.info(f"Updated empty user room snapshot for room_id={row.room_id}, year={year}, month={month}")
                continue
            else:
                history = UserRoomHistory(
                    area_id=row.area_id,
                    room_id=row.room_id,
                    room_name=row.room_name,
                    year=year,
                    month=month,
                    user_count=0,
                    created_at=current_time,
                    updated_at=current_time
                )
                db.session.add(history)

        db.session.commit()
        logger.info(f"Saved user room snapshot for {year}-{month}")
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving user room snapshot: {str(e)}")
        return False

def save_room_status_snapshot(target_year=None, target_month=None):
    try:
        current_time = datetime.utcnow()
        is_current_month = False
        if target_year and target_month:
            year = target_year
            month = target_month
            if year == current_time.year and month == current_time.month:
                is_current_month = True
        else:
            year = current_time.year
            month = current_time.month
            is_current_month = True

        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                Room.room_id,
                Room.name.label('room_name'),
                Room.status
            )
            .join(Area, Area.area_id == Room.area_id)
            .filter(Room.is_deleted == False)
        )

        results = query.all()

        for row in results:
            existing = RoomStatusHistory.query.filter_by(
                room_id=row.room_id, year=year, month=month
            ).first()
            if existing:
                if is_current_month:
                    existing.status = row.status
                    existing.updated_at = current_time
                    logger.info(f"Updated room status snapshot for room_id={row.room_id}, year={year}, month={month}")
                else:
                    logger.warning(f"Room status snapshot already exists for room_id={row.room_id}, year={year}, month={month}")
                    continue
            else:
                history = RoomStatusHistory(
                    area_id=row.area_id,
                    room_id=row.room_id,
                    room_name=row.room_name,
                    year=year,
                    month=month,
                    status=row.status,
                    created_at=current_time,
                    updated_at=current_time
                )
                db.session.add(history)

        db.session.commit()
        logger.info(f"Saved room status snapshot for {year}-{month}")
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving room status snapshot: {str(e)}")
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
            # Historical data
            if month:
                # Specific month
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
                # All months of the year
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
                results = query.all()

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
            # Real-time data
            current_time = datetime.utcnow()
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
                Room.is_deleted == False,
                Room.status == 'OCCUPIED',
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
                Contract.is_deleted == False,
                Contract.status == 'ACTIVE',
                Room.is_deleted == False
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
            .filter(User.is_deleted == False)
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
            # Historical data
            if month:
                # Specific month
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
                # All months of the year
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

                # Fill missing months with zero
                for area_data in response:
                    for m in range(1, 13):
                        if m not in area_data['months']:
                            area_data['months'][m] = 0
        else:
            # Real-time data for current year/month
            current_time = datetime.utcnow()
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
                .group_by(Area.area_id, Area.name)
            )

            if area_id:
                query = query.filter(Area.area_id == area_id)
            if room_id:
                query = query.filter(Room.room_id == room_id)

            results = query.all()

            response = {}
            for row in results:
                area_id = row[0]  # area_id
                if area_id not in response:
                    response[area_id] = {
                        'area_id': area_id,
                        'area_name': row[1],  # area_name
                        'months': {},
                        'total_users': 0
                    }
                response[area_id]['months'][int(row[3])] = row[2]  # month, user_count
                response[area_id]['total_users'] += row[2]  # user_count
            response = list(response.values())

            # Fill missing months with zero
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
        logger.error(f"Error in get_occupancy_rate_stats: {str(e)}")
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

@statistics_bp.route('/admin/save-snapshots', methods=['POST'], endpoint='statistics_save_snapshots')
@admin_required()
def save_snapshots():
    try:
        year = request.json.get('year', type=int)
        month = request.json.get('month', type=int)
        if year and month:
            if not (1 <= month <= 12):
                return jsonify({'status': 'error', 'message': 'Invalid month'}), 400
            if year < 2000 or year > datetime.utcnow().year:
                return jsonify({'status': 'error', 'message': 'Invalid year'}), 400
        save_room_status_snapshot(year=year, month=month)
        save_user_room_snapshot(year=year, month=month)
        return jsonify({
            'status': 'success',
            'message': f'Lưu snapshot thành công cho {year or "current year"}-{month or "previous month"}'
        }), 200
    except Exception as e:
        logger.error(f"Error saving snapshots: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Lỗi khi lưu snapshot: {str(e)}'
        }), 500