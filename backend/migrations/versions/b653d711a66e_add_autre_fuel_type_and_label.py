"""add AUTRE fuel type and label

Revision ID: b653d711a66e
Revises: 7bfaf3cbb3a6
Create Date: 2026-10-16 23:12:17.799889

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b653d711a66e'
down_revision: Union[str, Sequence[str], None] = '7bfaf3cbb3a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Écrit à la main : --autogenerate ne voit pas les changements de CheckConstraint.
# (table, colonne, nom de la contrainte) : la liste des carburants est vérifiée dans trois tables.
FUEL_TYPE_CHECKS = [
    ("fuels", "type", "fuel_type_allowed"),
    ("availability_events", "fuel_type", "event_fuel_type_allowed"),
    ("favorite_fuels", "fuel_type", "favorite_fuel_type_allowed"),
]
OLD_TYPES = "'GAZOLE', 'SP95', 'E10', 'SP98', 'E85', 'GPLC'"
NEW_TYPES = OLD_TYPES + ", 'AUTRE'"


def replace_fuel_type_checks(types: str) -> None:
    for table, column, name in FUEL_TYPE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"{column} IN ({types})")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('availability_events', sa.Column('label', sa.String(length=50), nullable=True))
    op.add_column('fuels', sa.Column('label', sa.String(length=50), nullable=True))
    replace_fuel_type_checks(NEW_TYPES)
    op.create_check_constraint("fuel_label_only_for_other", "fuels", "(type = 'AUTRE') = (label IS NOT NULL)")


def downgrade() -> None:
    """Downgrade schema."""
    # Les lignes AUTRE n'ont pas de place dans l'ancien schéma : elles sont supprimées.
    for table, column, _ in FUEL_TYPE_CHECKS:
        op.execute(f"DELETE FROM {table} WHERE {column} = 'AUTRE'")
    op.drop_constraint("fuel_label_only_for_other", "fuels", type_="check")
    replace_fuel_type_checks(OLD_TYPES)
    op.drop_column('fuels', 'label')
    op.drop_column('availability_events', 'label')
