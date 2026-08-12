"""added few things in db soft delete etc

Revision ID: e6cd211dd48c
Revises: e77ccf3908b8
Create Date: 2026-07-03 11:55:42.557377

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6cd211dd48c'
down_revision: Union[str, Sequence[str], None] = 'e77ccf3908b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
