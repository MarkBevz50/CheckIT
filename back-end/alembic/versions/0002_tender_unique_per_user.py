"""tenders: unique (user_id, prozorro_id) instead of a globally unique prozorro_id (E0.14)

Every user keeps their own copy of a tender with their own analysis, so two users may import the same
Prozorro tender. Before this revision the second import was refused with 409 (and revealed that someone
else had imported it).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-27

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # the new rule is weaker than the old one, so this always succeeds on existing data
    op.drop_index(op.f('ix_tenders_prozorro_id'), table_name='tenders')
    op.create_index(op.f('ix_tenders_prozorro_id'), 'tenders', ['prozorro_id'], unique=False)
    op.create_unique_constraint(op.f('uq_tenders_user_id_prozorro_id'), 'tenders', ['user_id', 'prozorro_id'])


def downgrade() -> None:
    if not context.is_offline_mode():
        duplicated = op.get_bind().execute(sa.text(
            "SELECT count(*) FROM (SELECT prozorro_id FROM tenders GROUP BY prozorro_id HAVING count(*) > 1) AS d"
        )).scalar()
        if duplicated:
            raise RuntimeError(
                f"Cannot downgrade: {duplicated} Prozorro ID(s) exist in more than one user's list, and the old "
                "schema allows each of them once. Remove or merge the copies first."
            )
    op.drop_constraint(op.f('uq_tenders_user_id_prozorro_id'), 'tenders', type_='unique')
    op.drop_index(op.f('ix_tenders_prozorro_id'), table_name='tenders')
    op.create_index(op.f('ix_tenders_prozorro_id'), 'tenders', ['prozorro_id'], unique=True)
