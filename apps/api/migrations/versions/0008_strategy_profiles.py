"""Global strategy profiles and bot overrides."""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_published_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_strategy_profiles_name", "strategy_profiles", ["name"])
    op.create_index("ix_strategy_profiles_status", "strategy_profiles", ["status"])
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("strategy_profile_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["strategy_profile_id"], ["strategy_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_profile_id", "version", name="uq_strategy_profile_version"),
    )
    op.create_index("ix_strategy_versions_strategy_profile_id", "strategy_versions", ["strategy_profile_id"])
    op.create_index("ix_strategy_versions_status", "strategy_versions", ["status"])
    op.add_column("bots", sa.Column("strategy_version_id", sa.Uuid(), nullable=True))
    op.add_column("bots", sa.Column("config_overrides", sa.JSON(), nullable=False, server_default="{}"))
    op.create_foreign_key("fk_bots_strategy_version", "bots", "strategy_versions", ["strategy_version_id"], ["id"])
    op.create_index("ix_bots_strategy_version_id", "bots", ["strategy_version_id"])
    op.add_column("config_versions", sa.Column("strategy_version_id", sa.Uuid(), nullable=True))
    op.add_column("config_versions", sa.Column("config_overrides", sa.JSON(), nullable=False, server_default="{}"))
    op.create_foreign_key("fk_config_versions_strategy_version", "config_versions", "strategy_versions", ["strategy_version_id"], ["id"])
    op.create_index("ix_config_versions_strategy_version_id", "config_versions", ["strategy_version_id"])


def downgrade() -> None:
    op.drop_index("ix_config_versions_strategy_version_id", table_name="config_versions")
    op.drop_constraint("fk_config_versions_strategy_version", "config_versions", type_="foreignkey")
    op.drop_column("config_versions", "config_overrides")
    op.drop_column("config_versions", "strategy_version_id")
    op.drop_index("ix_bots_strategy_version_id", table_name="bots")
    op.drop_constraint("fk_bots_strategy_version", "bots", type_="foreignkey")
    op.drop_column("bots", "config_overrides")
    op.drop_column("bots", "strategy_version_id")
    op.drop_table("strategy_versions")
    op.drop_table("strategy_profiles")
