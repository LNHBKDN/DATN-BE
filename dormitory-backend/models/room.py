from extensions import db

class Room(db.Model):
    __tablename__ = 'rooms'
    room_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    capacity = db.Column(db.SmallInteger, nullable=False)
    price = db.Column(db.DECIMAL(12, 2), nullable=False)
    current_person_number = db.Column(db.Integer, default=0, nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.Enum('AVAILABLE', 'OCCUPIED', 'MAINTENANCE', 'DISABLED'), default='AVAILABLE', nullable=False)
    area_id = db.Column(db.Integer, db.ForeignKey('area.area_id', ondelete='RESTRICT'), nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)
    
    area = db.relationship('Area', backref='rooms', lazy=True)
    bills = db.relationship('MonthlyBill', back_populates='room', lazy=True)

    ALLOWED_STATUSES = ['AVAILABLE', 'OCCUPIED', 'MAINTENANCE', 'DISABLED']
    
    def to_dict(self):
        return {
            'room_id': self.room_id,
            'name': self.name,
            'capacity': self.capacity,
            'price': str(self.price),
            'current_person_number': self.current_person_number,
            'description': self.description,
            'status': self.status,
            'area_id': self.area_id,
            'area_details': {
                'area_id': self.area.area_id,
                'name': self.area.name
            } if self.area else None
        }