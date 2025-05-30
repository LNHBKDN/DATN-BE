from extensions import db
from models.room import Room
class BillDetail(db.Model):
    __tablename__ = 'bill_details'
    detail_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    rate_id = db.Column(db.BigInteger, db.ForeignKey('service_rates.rate_id', ondelete='RESTRICT'), nullable=False)
    previous_reading = db.Column(db.DECIMAL(10, 2), default=0.00, nullable=False)
    current_reading = db.Column(db.DECIMAL(10, 2), default=0.00, nullable=False)
    price = db.Column(db.DECIMAL(10, 2), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.room_id', ondelete='RESTRICT'), nullable=False)
    bill_month = db.Column(db.Date, nullable=False)
    submitted_by = db.Column(db.BigInteger, db.ForeignKey('users.user_id'), nullable=True)
    submitted_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=True)
    
    rate = db.relationship('ServiceRate', back_populates='details', lazy=True)
    submitter = db.relationship('User', back_populates='submitted_bill_details', lazy=True)
    monthly_bill = db.relationship('MonthlyBill', back_populates='bill_detail', uselist=False, lazy=True)

    def to_dict(self):
        # Query the Room table to get the room's name based on room_id
        room = Room.query.filter_by(room_id=self.room_id).first()
        room_name = room.name if room else 'N/A'

        return {
            'detail_id': self.detail_id,
            'rate_id': self.rate_id,
            'previous_reading': str(self.previous_reading),
            'current_reading': str(self.current_reading),
            'price': str(self.price),
            'room_id': self.room_id,
            'room_name': room_name,  # Include the room name
            'bill_month': self.bill_month.isoformat() if self.bill_month else None,
            'submitted_by': self.submitted_by,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'rate_details': {
                'rate_id': self.rate.rate_id,
                'unit_price': str(self.rate.unit_price),
                'effective_date': self.rate.effective_date.isoformat() if self.rate.effective_date else None,
                'service_id': self.rate.service_id,
                'service_name': self.rate.service.name if self.rate and self.rate.service else None
            } if self.rate else None,
            'submitter_details': {
                'user_id': self.submitter.user_id,
                'fullname': self.submitter.fullname,
                'email': self.submitter.email
            } if self.submitter else None,
            'monthly_bill_id': self.monthly_bill.bill_id if self.monthly_bill else None
        }