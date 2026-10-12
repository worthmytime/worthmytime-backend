"""budget rollover

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ('rollover_since_needs', 'rollover_since_future', 'rollover_since_goals', 'rollover_since_fun')


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('budgets', schema=None) as batch_op:
        for name in COLUMNS:
            batch_op.add_column(sa.Column(name, sa.String(length=7), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('budgets', schema=None) as batch_op:
        for name in reversed(COLUMNS):
            batch_op.drop_column(name)
