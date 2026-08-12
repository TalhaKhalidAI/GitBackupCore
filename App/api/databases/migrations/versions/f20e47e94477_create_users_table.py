"""Create users table

Revision ID: f20e47e94477
Revises: 7c06030f5e89
Create Date: 2026-07-02 18:36:54.014515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f20e47e94477'
down_revision: Union[str, Sequence[str], None] = '7c06030f5e89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
