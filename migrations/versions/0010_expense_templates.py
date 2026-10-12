"""expense templates

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'expense_templates',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=10), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('expense_templates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_expense_templates_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('expense_templates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_expense_templates_user_id'))

    op.drop_table('expense_templates')
