from extensions import db

class Service(db.Model):
    __tablename__ = 'services'
    service_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), unique=True, nullable=False, comment='ví dụ: Điện, Nước')
    unit = db.Column(db.String(10), nullable=False, comment='ví dụ: kWh, m3, Month')

    rates = db.relationship('ServiceRate', back_populates='service', lazy=True)

    def to_dict(self):
        return {
            'service_id': self.service_id,
            'name': self.name,
            'unit': self.unit
        }