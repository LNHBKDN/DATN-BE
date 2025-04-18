from extensions import db

class Area(db.Model):
    __tablename__ = 'area'
    area_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    def to_dict(self):
        return {
            'area_id': self.area_id,
            'name': self.name
        }