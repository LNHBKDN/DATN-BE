from flask import Blueprint, request, jsonify, current_app, redirect
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from models.payment_transaction import PaymentTransaction
from models.monthly_bill import MonthlyBill
from models.user import User
from controllers.auth_controller import admin_required, user_required
import hashlib
import hmac
import urllib.parse
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
import logging

payment_transaction_bp = Blueprint('payment_transaction', __name__)

# Hàm tiện ích để mã hóa giá trị URL
def encode_url_value(value):
    return urllib.parse.quote_plus(str(value))

# Hàm tiện ích để tạo chữ ký bảo mật
def generate_secure_hash(data, secret_key):
    if not secret_key:
        raise ValueError("Secret key không được để trống")
    data_string = '&'.join([f"{k}={encode_url_value(v)}" for k, v in sorted(data.items())])
    logging.debug(f"Data string for hash: {data_string}")
    return hmac.new(secret_key.encode('utf-8'), data_string.encode('utf-8'), hashlib.sha512).hexdigest()

# Hàm tiện ích để lấy thông tin người dùng từ JWT
def get_user_info(identity):
    try:
        if isinstance(identity, dict):
            return identity['id'], identity.get('type', 'USER')
        return int(identity), 'USER'
    except (TypeError, ValueError) as e:
        raise ValueError(f"Token không hợp lệ: {str(e)}")

# Hàm tạo VNPay params và URL
def create_vnpay_url(transaction, bill_id, payment_method, return_url, request_ip):
    VNPAY_TMN_CODE = current_app.config.get("VNPAY_TMN_CODE")
    VNPAY_HASH_SECRET = current_app.config.get("VNPAY_HASH_SECRET")
    VNPAY_URL = current_app.config.get("VNPAY_URL", "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html")

    if not all([VNPAY_TMN_CODE, VNPAY_HASH_SECRET, VNPAY_URL]):
        raise ValueError("Cấu hình VNPay không đầy đủ")

    create_date = datetime.now()
    expire_date = create_date + timedelta(minutes=15)

    vnp_params = {
        'vnp_Version': '2.1.0',
        'vnp_Command': 'pay',
        'vnp_TmnCode': VNPAY_TMN_CODE,
        'vnp_Amount': int(float(transaction.amount) * 100),
        'vnp_CurrCode': 'VND',
        'vnp_TxnRef': str(transaction.transaction_id),
        'vnp_OrderInfo': f'Payment for bill {bill_id}',
        'vnp_OrderType': 'billpayment',
        'vnp_Locale': 'vn',
        'vnp_ReturnUrl': return_url,
        'vnp_IpAddr': request_ip,
        'vnp_CreateDate': create_date.strftime('%Y%m%d%H%M%S'),
        'vnp_ExpireDate': expire_date.strftime('%Y%m%d%H%M%S'),
    }

    logging.debug(f"VNPay params before hash: {vnp_params}")
    vnp_params['vnp_SecureHash'] = generate_secure_hash(vnp_params, VNPAY_HASH_SECRET)
    logging.debug(f"VNPay SecureHash: {vnp_params['vnp_SecureHash']}")
    vnpay_url = f"{VNPAY_URL}?{urllib.parse.urlencode(vnp_params)}"
    logging.debug(f"Generated VNPay URL: {vnpay_url}")
    return vnpay_url

# Tạo giao dịch mới
@payment_transaction_bp.route('/payment-transactions', methods=['POST'])
@jwt_required()
def create_payment_transaction():
    logging.info("POST /payment-transactions")
    try:
        user_id, user_type = get_user_info(get_jwt_identity())

        data = request.get_json()
        bill_id = data.get('bill_id')
        payment_method = data.get('payment_method')
        ngrok_url = current_app.config.get("NGROK_URL")
        return_url = data.get('return_url', f"{ngrok_url}/api/payment-transactions/callback")

        if not all([bill_id, payment_method]):
            return jsonify({'message': 'Yêu cầu bill_id và payment_method'}), 400

        if not return_url.startswith('https://'):
            return jsonify({'message': 'Return URL phải sử dụng HTTPS'}), 400

        bill = MonthlyBill.query.get(bill_id)
        if not bill:
            return jsonify({'message': 'Không tìm thấy hóa đơn'}), 404

        if user_type == 'USER':
            user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
            if not user or bill.user_id != user_id or not any(
                contract.room_id == bill.room_id and contract.status == 'ACTIVE' for contract in user.contracts
            ):
                return jsonify({'message': 'Bạn không có quyền thanh toán hóa đơn này'}), 403

        if bill.payment_status == 'PAID':
            return jsonify({'message': 'Hóa đơn đã được thanh toán'}), 409

        amount = float(bill.total_amount)
        if amount <= 0:
            return jsonify({'message': 'Số tiền hóa đơn không hợp lệ'}), 400
        if amount > 50000000:
            return jsonify({'message': 'Số tiền vượt quá giới hạn sandbox VNPay (50 triệu VND)'}), 400

        allowed_methods = bill.payment_method_allowed.split(',') if bill.payment_method_allowed else []
        if payment_method not in allowed_methods:
            return jsonify({'message': f'Phương thức thanh toán {payment_method} không được phép'}), 400

        existing_transaction = PaymentTransaction.query.filter_by(
            bill_id=bill_id, status='PENDING'
        ).first()

        if existing_transaction:
            if bill.payment_status != 'PENDING':
                return jsonify({'message': 'Hóa đơn không còn ở trạng thái PENDING'}), 409
            if existing_transaction.created_at < datetime.utcnow() - timedelta(minutes=15):
                existing_transaction.status = 'CANCELLED'
                db.session.commit()
                logging.info(f"Cancelled expired PaymentTransaction {existing_transaction.transaction_id} for bill {bill_id}")
            else:
                existing_transaction.status = 'CANCELLED'
                db.session.commit()
                logging.info(f"Cancelled PaymentTransaction {existing_transaction.transaction_id} to create a new one for bill {bill_id}")

        transaction = PaymentTransaction(
            bill_id=bill_id,
            amount=amount,
            payment_method=payment_method.upper(),
            status='PENDING'
        )
        db.session.add(transaction)
        db.session.commit()

        vnpay_url = create_vnpay_url(transaction, bill_id, payment_method, return_url, request.remote_addr)
        logging.info(f"User {user_id} created PaymentTransaction {transaction.transaction_id} for bill {bill_id}")
        return jsonify({
            'payment_url': vnpay_url,
            'transaction_id': transaction.transaction_id,
            'bill_details': {'bill_id': bill.bill_id, 'total_amount': str(bill.total_amount)}
        }), 200

    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError: {str(e)}")
        return jsonify({'message': 'Lỗi khi tạo giao dịch: Hóa đơn không hợp lệ'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error: {str(e)}")
        return jsonify({'message': 'Lỗi khi tạo giao dịch thanh toán', 'error': str(e)}), 500

# Xử lý callback từ VNPay
@payment_transaction_bp.route('/payment-transactions/callback', methods=['GET'])
def vnpay_callback():
    logging.info("GET /payment-transactions/callback")
    try:
        vnp_params = request.args.to_dict()
        secure_hash = vnp_params.pop('vnp_SecureHash', None)
        if not secure_hash:
            return jsonify({'message': 'Invalid signature'}), 400

        VNPAY_HASH_SECRET = current_app.config.get("VNPAY_HASH_SECRET")
        calculated_hash = generate_secure_hash(vnp_params, VNPAY_HASH_SECRET)

        if secure_hash != calculated_hash:
            return jsonify({'message': 'Signature mismatch'}), 400

        transaction_id = vnp_params.get('vnp_TxnRef')
        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            return jsonify({'message': 'Transaction not found'}), 404

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            return jsonify({'message': 'Bill not found'}), 404

        logging.info(f"Before update - Transaction {transaction_id} status: {transaction.status}, Bill {bill.bill_id} payment_status: {bill.payment_status}")

        if vnp_params.get('vnp_ResponseCode') == '00':
            transaction.status = 'SUCCESS'
            transaction.processed_at = datetime.utcnow()
            transaction.gateway_reference = vnp_params.get('vnp_TransactionNo')
            bill.payment_status = 'PAID'
            bill.paid_at = datetime.utcnow()
            bill.transaction_reference = transaction.gateway_reference
        else:
            transaction.status = 'FAILED'
            transaction.error_message = vnp_params.get('vnp_Message', 'Payment failed')
            bill.payment_status = 'FAILED'

        db.session.commit()

        logging.info(f"After update - Transaction {transaction_id} status: {transaction.status}, Bill {bill.bill_id} payment_status: {bill.payment_status}")

        # Tạo redirect URL với các tham số bổ sung
        ngrok_url = current_app.config.get("NGROK_URL")
        redirect_base = f"{ngrok_url}/payment/success" if transaction.status == 'SUCCESS' else f"{ngrok_url}/payment/failure"
        
        redirect_params = {
            'transaction_id': transaction_id,
            'status': transaction.status,
            'bank_code': vnp_params.get('vnp_BankCode', ''),
            'transaction_no': vnp_params.get('vnp_TransactionNo', ''),
            'pay_date': vnp_params.get('vnp_PayDate', ''),
            'amount': int(vnp_params.get('vnp_Amount', 0)) / 100  # Chia 100 để trả về VND
        }
        redirect_url = f"{redirect_base}?{urllib.parse.urlencode(redirect_params)}"

        logging.info(f"Redirecting to: {redirect_url}")
        return redirect(redirect_url)

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in vnpay_callback: {str(e)}")
        return jsonify({'message': 'Error processing callback', 'error': str(e)}), 500

# Xử lý trang thành công
@payment_transaction_bp.route('/payment/success', methods=['GET'])
def payment_success():
    try:
        # Lấy các tham số từ query string
        transaction_id = request.args.get('transaction_id')
        status = request.args.get('status')
        bank_code = request.args.get('bank_code')
        transaction_no = request.args.get('transaction_no')
        pay_date = request.args.get('pay_date')
        amount = float(request.args.get('amount', 0))

        # Tạo JSON response với thông tin chi tiết
        response_data = {
            'message': 'Payment processed successfully',
            'transaction_id': transaction_id,
            'status': status,
            'bank_code': bank_code,
            'transaction_no': transaction_no,
            'pay_date': pay_date,
            'amount': amount
        }

        logging.info(f"Payment success response: {response_data}")
        return jsonify(response_data), 200

    except Exception as e:
        logging.error(f"Error in payment_success: {str(e)}")
        return jsonify({'message': 'Error processing payment success', 'error': str(e)}), 500

# Xử lý trang thất bại
@payment_transaction_bp.route('/payment/failure', methods=['GET'])
def payment_failure():
    try:
        # Lấy các tham số từ query string
        transaction_id = request.args.get('transaction_id')
        status = request.args.get('status')
        bank_code = request.args.get('bank_code')
        transaction_no = request.args.get('transaction_no')
        pay_date = request.args.get('pay_date')
        amount = float(request.args.get('amount', 0))

        # Tạo JSON response với thông tin chi tiết
        response_data = {
            'message': 'Payment processing failed',
            'transaction_id': transaction_id,
            'status': status,
            'bank_code': bank_code,
            'transaction_no': transaction_no,
            'pay_date': pay_date,
            'amount': amount
        }

        logging.info(f"Payment failure response: {response_data}")
        return jsonify(response_data), 200

    except Exception as e:
        logging.error(f"Error in payment_failure: {str(e)}")
        return jsonify({'message': 'Error processing payment failure', 'error': str(e)}), 500

# Lấy danh sách giao dịch (Admin)
@payment_transaction_bp.route('/payment-transactions', methods=['GET'])
@admin_required()
def get_all_payment_transactions():
    logging.info("GET /payment-transactions")
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        bill_id = request.args.get('bill_id', type=int)
        status = request.args.get('status', type=str)

        if page <= 0 or limit <= 0:
            return jsonify({'message': 'Page and limit must be greater than 0'}), 400

        if status and status.upper() not in ['PENDING', 'SUCCESS', 'FAILED', 'CANCELLED']:
            return jsonify({'message': 'Invalid status'}), 400

        query = PaymentTransaction.query
        if bill_id:
            query = query.filter_by(bill_id=bill_id)
        if status:
            query = query.filter_by(status=status.upper())

        transactions = query.paginate(page=page, per_page=limit, error_out=False)
        return jsonify({
            'payment_transactions': [transaction.to_dict() for transaction in transactions.items],
            'total': transactions.total,
            'pages': transactions.pages,
            'current_page': transactions.page
        }), 200

    except Exception as e:
        logging.error(f"Error in get_all_payment_transactions: {str(e)}")
        return jsonify({'message': 'Error retrieving transactions', 'error': str(e)}), 500

# Lấy chi tiết giao dịch
@payment_transaction_bp.route('/payment-transactions/<int:transaction_id>', methods=['GET'])
@jwt_required()
def get_payment_transaction_by_id(transaction_id):
    logging.info(f"GET /payment-transactions/{transaction_id}")
    try:
        user_id, user_type = get_user_info(get_jwt_identity())

        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            return jsonify({'message': 'Transaction not found'}), 404

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            return jsonify({'message': 'Bill not found'}), 404

        if user_type == 'USER' and bill.user_id != user_id:
            return jsonify({'message': 'You do not have permission to view this transaction'}), 403

        return jsonify(transaction.to_dict()), 200

    except ValueError as e:
        return jsonify({'message': str(e)}), 401
    except Exception as e:
        logging.error(f"Error in get_payment_transaction_by_id: {str(e)}")
        return jsonify({'message': 'Error retrieving transaction details', 'error': str(e)}), 500

# Cập nhật giao dịch (Admin)
# @payment_transaction_bp.route('/payment-transactions/<int:transaction_id>', methods=['PUT'])
@admin_required()
def update_payment_transaction(transaction_id):
    logging.info(f"PUT /payment-transactions/{transaction_id}")
    try:
        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            return jsonify({'message': 'Transaction not found'}), 404

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            return jsonify({'message': 'Bill not found'}), 404

        if transaction.status != 'PENDING':
            return jsonify({'message': 'Cannot update: Transaction is not in PENDING status'}), 409

        data = request.get_json()
        new_payment_method = data.get('payment_method', transaction.payment_method).upper()
        new_status = data.get('status', transaction.status).upper() if data.get('status') else transaction.status

        if new_payment_method not in ['VIETQR', 'CASH', 'BANK_TRANSFER']:
            return jsonify({'message': f'Invalid payment method: {new_payment_method}'}), 400

        if new_status not in ['PENDING', 'SUCCESS', 'FAILED', 'CANCELLED']:
            return jsonify({'message': 'Invalid status'}), 400

        transaction.payment_method = new_payment_method
        transaction.status = new_status

        if new_status == 'SUCCESS':
            bill.payment_status = 'PAID'
            bill.paid_at = datetime.utcnow()
            bill.transaction_reference = transaction.gateway_reference or f"TRANS-{transaction.transaction_id}"
        elif new_status == 'FAILED':
            bill.payment_status = 'FAILED'
            bill.transaction_reference = None

        db.session.commit()
        logging.info(f"Updated PaymentTransaction {transaction_id} to status {new_status}")
        return jsonify(transaction.to_dict()), 200

    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError in update_payment_transaction: {str(e)}")
        return jsonify({'message': 'Error updating transaction: Data conflict'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in update_payment_transaction: {str(e)}")
        return jsonify({'message': 'Error updating transaction', 'error': str(e)}), 500

# Xóa giao dịch (Admin)
# @payment_transaction_bp.route('/payment-transactions/<int:transaction_id>', methods=['DELETE'])
@admin_required()
def delete_payment_transaction(transaction_id):
    logging.info(f"DELETE /payment-transactions/{transaction_id}")
    try:
        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            return jsonify({'message': 'Transaction not found'}), 404

        if transaction.status == 'SUCCESS':
            return jsonify({'message': 'Cannot delete: Transaction is successful'}), 409

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            return jsonify({'message': 'Bill not found'}), 404

        db.session.delete(transaction)
        db.session.commit()
        logging.info(f"Deleted PaymentTransaction {transaction_id}")
        return '', 204

    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError in delete_payment_transaction: {str(e)}")
        return jsonify({'message': 'Error deleting transaction: Data conflict'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in delete_payment_transaction: {str(e)}")
        return jsonify({'message': 'Error deleting transaction', 'error': str(e)}), 500