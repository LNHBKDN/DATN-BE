from extensions import db
from datetime import datetime

class RoomStatusHistory(db.Model):
    __tablename__ = 'room_status_history'

    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey('area.area_id', ondelete='RESTRICT', onupdate='CASCADE'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.room_id', ondelete='RESTRICT', onupdate='CASCADE'), nullable=False)
    room_name = db.Column(db.String(255), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    area = db.relationship('Area', backref='room_status_histories')
    room = db.relationship('Room', backref='status_histories')

    __table_args__ = (
        db.UniqueConstraint('room_id', 'year', 'month', name='uq_room_status_history'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'area_id': self.area_id,
            'area_name': self.area.name if self.area else None,
            'room_id': self.room_id,
            'room_name': self.room_name,
            'year': self.year,
            'month': self.month,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }