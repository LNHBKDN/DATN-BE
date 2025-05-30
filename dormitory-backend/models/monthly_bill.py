from extensions import db

class MonthlyBill(db.Model):
    __tablename__ = 'monthly_bills'
    bill_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.user_id', ondelete='RESTRICT'), nullable=False)
    detail_id = db.Column(db.BigInteger, db.ForeignKey('bill_details.detail_id', ondelete='RESTRICT'), nullable=False, unique=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.room_id', ondelete='RESTRICT'), nullable=False)
    bill_month = db.Column(db.Date, nullable=False)
    total_amount = db.Column(db.DECIMAL(12, 2), default=0.00, nullable=False)
    payment_status = db.Column(db.Enum('PENDING', 'PAID', 'FAILED', 'OVERDUE'), default='PENDING', nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=False)
    payment_method_allowed = db.Column(db.String(255), nullable=True)
    paid_at = db.Column(db.TIMESTAMP, nullable=True)
    transaction_reference = db.Column(db.String(255), nullable=True)
    
    user = db.relationship('User', back_populates='bills', lazy=True)
    room = db.relationship('Room', back_populates='bills', lazy=True)
    bill_detail = db.relationship('BillDetail', back_populates='monthly_bill', uselist=False, lazy='joined')

    def to_dict(self):
        # Lấy service_name từ bill_detail → rate → service
        service_name = None
        if self.bill_detail and self.bill_detail.rate and self.bill_detail.rate.service:
            service_name = self.bill_detail.rate.service.name

        return {
            'bill_id': self.bill_id,
            'user_id': self.user_id,
            'detail_id': self.detail_id,
            'room_id': self.room_id,
            'bill_month': self.bill_month.isoformat() if self.bill_month else None,
            'total_amount': str(self.total_amount),
            'payment_status': self.payment_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'payment_method_allowed': self.payment_method_allowed,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'transaction_reference': self.transaction_reference,
            'user_details': {
                'user_id': self.user.user_id,
                'fullname': self.user.fullname,
                'email': self.user.email
            } if self.user else None,
            'room_details': {
                'room_id': self.room.room_id,
                'name': self.room.name
            } if self.room else None,
            'bill_detail_id': self.bill_detail.detail_id if self.bill_detail else None,
            'service_name': service_name  # Thêm service_name
        }