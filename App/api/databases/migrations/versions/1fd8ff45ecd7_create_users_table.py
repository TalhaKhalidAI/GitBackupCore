"""Create users table

Revision ID: 1fd8ff45ecd7
Revises: f20e47e94477
Create Date: 2026-07-02 18:40:09.563770

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1fd8ff45ecd7'
down_revision: Union[str, Sequence[str], None] = 'f20e47e94477'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
