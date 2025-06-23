"""add hometown and student_code to users

Revision ID: 0dfd00cdd561
Revises: a1b2c3d4e5f6
Create Date: 2025-06-20 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0dfd00cdd561'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hometown', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('student_code', sa.String(length=20), nullable=True))
        batch_op.create_unique_constraint('uq_users_student_code', ['student_code'])

def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_student_code', type_='unique')
        batch_op.drop_column('student_code')
        batch_op.drop_column('hometown')