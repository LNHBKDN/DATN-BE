from extensions import db

class ServiceRate(db.Model):
    __tablename__ = 'service_rates'
    rate_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    unit_price = db.Column(db.DECIMAL(10, 2), nullable=False)
    effective_date = db.Column(db.Date, nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('services.service_id', ondelete='RESTRICT'), nullable=False)
    
    service = db.relationship('Service', back_populates='rates', lazy=True)
    details = db.relationship('BillDetail', back_populates='rate', lazy=True)

    def to_dict(self):
        return {
            'rate_id': self.rate_id,
            'unit_price': str(self.unit_price),
            'effective_date': self.effective_date.isoformat() if self.effective_date else None,
            'service_id': self.service_id,
            'service_name': self.service.name if self.service else None  # Thêm service_name
        }