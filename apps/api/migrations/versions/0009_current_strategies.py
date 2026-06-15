"""Store only the current strategy configuration."""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    op.add_column("strategy_profiles", sa.Column("config", sa.JSON(), nullable=True))
    op.add_column("bots", sa.Column("strategy_profile_id", sa.Uuid(), nullable=True))
    op.add_column("bots", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("config_versions", sa.Column("strategy_profile_id", sa.Uuid(), nullable=True))

    connection.execute(
        sa.text(
            """
            UPDATE strategy_profiles
            SET config = COALESCE(
                (
                    SELECT sv.config
                    FROM strategy_versions sv
                    WHERE sv.id = strategy_profiles.current_published_version_id
                ),
                (
                    SELECT sv.config
                    FROM strategy_versions sv
                    WHERE sv.strategy_profile_id = strategy_profiles.id
                    ORDER BY sv.version DESC
                    LIMIT 1
                )
            ),
            status = CASE WHEN status = 'ARCHIVED' THEN status ELSE 'ACTIVE' END
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE bots
            SET strategy_profile_id = (
                SELECT sv.strategy_profile_id
                FROM strategy_versions sv
                WHERE sv.id = bots.strategy_version_id
            )
            WHERE strategy_version_id IS NOT NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE config_versions
            SET strategy_profile_id = (
                SELECT sv.strategy_profile_id
                FROM strategy_versions sv
                WHERE sv.id = config_versions.strategy_version_id
            )
            WHERE strategy_version_id IS NOT NULL
            """
        )
    )
    op.alter_column("strategy_profiles", "config", nullable=False)
    op.create_foreign_key(
        "fk_bots_strategy_profile",
        "bots",
        "strategy_profiles",
        ["strategy_profile_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_config_versions_strategy_profile",
        "config_versions",
        "strategy_profiles",
        ["strategy_profile_id"],
        ["id"],
    )
    op.create_index("ix_bots_strategy_profile_id", "bots", ["strategy_profile_id"])
    op.create_index("ix_bots_archived_at", "bots", ["archived_at"])
    op.create_index(
        "ix_config_versions_strategy_profile_id",
        "config_versions",
        ["strategy_profile_id"],
    )

    op.drop_index("ix_config_versions_strategy_version_id", table_name="config_versions")
    op.drop_constraint(
        "fk_config_versions_strategy_version", "config_versions", type_="foreignkey"
    )
    op.drop_column("config_versions", "strategy_version_id")
    op.drop_index("ix_bots_strategy_version_id", table_name="bots")
    op.drop_constraint("fk_bots_strategy_version", "bots", type_="foreignkey")
    op.drop_column("bots", "strategy_version_id")
    op.drop_column("strategy_profiles", "current_published_version_id")
    op.drop_table("strategy_versions")


def downgrade() -> None:
    raise RuntimeError("Strategy version removal cannot be downgraded safely")
