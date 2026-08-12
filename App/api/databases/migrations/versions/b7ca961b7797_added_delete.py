"""added delete

Revision ID: b7ca961b7797
Revises: e6cd211dd48c
Create Date: 2026-07-03 12:40:19.404984

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7ca961b7797'
down_revision: Union[str, Sequence[str], None] = 'e6cd211dd48c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
