"""goal deposits

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-12 16:00:00.000000

"""
import uuid
from datetime import UTC, date, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    table = op.create_table(
        'goal_deposits',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('goal_id', sa.String(length=36), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
        sa.Column('deposited_on', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['goal_id'], ['savings_goals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('goal_deposits', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_goal_deposits_deposited_on'), ['deposited_on'], unique=False)
        batch_op.create_index(batch_op.f('ix_goal_deposits_goal_id'), ['goal_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_goal_deposits_user_id'), ['user_id'], unique=False)

    # dotychczas odłożone kwoty stają się jedną wpłatą z datą utworzenia celu (dokładniejszej historii nie ma)
    goals = op.get_bind().execute(
        sa.text("SELECT id, user_id, saved_amount, created_at FROM savings_goals WHERE saved_amount > 0")
    )
    now = datetime.now(UTC)
    rows = [
        {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'goal_id': goal_id,
            'amount': float(saved),
            # SQLite zwraca datę jako tekst, PostgreSQL jako datetime
            'deposited_on': date.fromisoformat(str(created_at)[:10]),
            'created_at': now,
        }
        for goal_id, user_id, saved, created_at in goals
    ]
    if rows:
        op.bulk_insert(table, rows)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('goal_deposits', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_goal_deposits_user_id'))
        batch_op.drop_index(batch_op.f('ix_goal_deposits_goal_id'))
        batch_op.drop_index(batch_op.f('ix_goal_deposits_deposited_on'))

    op.drop_table('goal_deposits')
