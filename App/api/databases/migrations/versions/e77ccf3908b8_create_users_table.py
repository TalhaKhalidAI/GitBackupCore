"""Create users table

Revision ID: e77ccf3908b8
Revises: 1fd8ff45ecd7
Create Date: 2026-07-02 18:47:03.135525

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e77ccf3908b8'
down_revision: Union[str, Sequence[str], None] = '1fd8ff45ecd7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
