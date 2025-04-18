from extensions import db

class ReportType(db.Model):
    __tablename__ = 'report_type'
    report_type_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=True)

    def to_dict(self):
        return {
            'report_type_id': self.report_type_id,
            'name': self.name
        }