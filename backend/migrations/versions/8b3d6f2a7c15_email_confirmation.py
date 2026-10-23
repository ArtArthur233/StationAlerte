"""email confirmation: users.email_verified_at, email_confirmation_tokens, auth_attempts kind 'confirm'

Revision ID: 8b3d6f2a7c15
Revises: 5c2e8a1f9d40
Create Date: 2026-10-17

Écrite à la main : --autogenerate ne voit pas le changement de la contrainte CHECK auth_attempt_kind_allowed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8b3d6f2a7c15'
down_revision: Union[str, Sequence[str], None] = '5c2e8a1f9d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    # Comptes créés avant la confirmation par e-mail : considérés confirmés (sinon leurs propriétaires,
    # dont l'auteur du projet, ne pourraient plus se connecter).
    op.execute("UPDATE users SET email_verified_at = now()")
    op.create_table(
        'email_confirmation_tokens',
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token_hash'),
    )
    op.create_index(op.f('ix_email_confirmation_tokens_user_id'), 'email_confirmation_tokens', ['user_id'])
    op.drop_constraint('auth_attempt_kind_allowed', 'auth_attempts', type_='check')
    op.create_check_constraint('auth_attempt_kind_allowed', 'auth_attempts', "kind IN ('login', 'register', 'reset', 'confirm')")


def downgrade() -> None:
    op.execute("DELETE FROM auth_attempts WHERE kind = 'confirm'")
    op.drop_constraint('auth_attempt_kind_allowed', 'auth_attempts', type_='check')
    op.create_check_constraint('auth_attempt_kind_allowed', 'auth_attempts', "kind IN ('login', 'register', 'reset')")
    op.drop_index(op.f('ix_email_confirmation_tokens_user_id'), table_name='email_confirmation_tokens')
    op.drop_table('email_confirmation_tokens')
    op.drop_column('users', 'email_verified_at')
