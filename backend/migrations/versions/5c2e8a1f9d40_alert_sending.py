"""alert sending: statuses, attempts, sent_at, last_error

Revision ID: 5c2e8a1f9d40
Revises: f9e4f790802f
Create Date: 2026-10-17

Écrite à la main : --autogenerate ne voit pas le changement de la contrainte CHECK alert_status_allowed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5c2e8a1f9d40'
down_revision: Union[str, Sequence[str], None] = 'f9e4f790802f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('alerts', sa.Column('attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('alerts', sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('alerts', sa.Column('last_error', sa.String(length=200), nullable=True))
    op.drop_constraint('alert_status_allowed', 'alerts', type_='check')
    op.create_check_constraint('alert_status_allowed', 'alerts', "status IN ('pending', 'sent', 'failed', 'expired')")
    op.create_index('alerts_pending', 'alerts', ['user_id'], postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index('alerts_pending', table_name='alerts', postgresql_where=sa.text("status = 'pending'"))
    # Les alertes déjà traitées n'existaient pas avant : on les supprime pour pouvoir remettre l'ancienne règle.
    op.execute("DELETE FROM alerts WHERE status <> 'pending'")
    op.drop_constraint('alert_status_allowed', 'alerts', type_='check')
    op.create_check_constraint('alert_status_allowed', 'alerts', "status IN ('pending')")
    op.drop_column('alerts', 'last_error')
    op.drop_column('alerts', 'sent_at')
    op.drop_column('alerts', 'attempts')
