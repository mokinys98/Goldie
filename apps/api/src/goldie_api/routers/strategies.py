import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from goldie_domain import BotConfiguration, strategy_catalog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Bot, ConfigVersion, MarketFeed, StrategyProfile, User
from ..schemas import StrategyProfileCreate, StrategyProfileRead, StrategyProfileUpdate
from ..security import get_current_user
from ..services import (
    activate_config_version,
    add_audit,
    effective_strategy_config,
    next_config_version,
)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])
profiles = APIRouter(prefix="/api/v1/strategy-profiles", tags=["strategy-profiles"])


@router.get("")
def list_strategies(_: User = Depends(get_current_user)) -> list[dict]:
    return strategy_catalog()


@router.get("/configuration-schema")
def configuration_schema(_: User = Depends(get_current_user)) -> dict:
    schema = BotConfiguration.model_json_schema()

    def resolve(value: dict) -> dict:
        ref = value.get("$ref")
        return schema["$defs"][ref.rsplit("/", 1)[-1]] if ref else value

    sections: dict[str, dict] = {}
    for section_name, section_value in schema["properties"].items():
        section = resolve(section_value)
        fields = {}
        for field_name, field_value in section.get("properties", {}).items():
            if section_name == "strategy" and field_name == "parameters":
                continue
            fields[field_name] = {
                key: value
                for key, value in field_value.items()
                if key
                in {
                    "title",
                    "description",
                    "type",
                    "minimum",
                    "maximum",
                    "exclusiveMinimum",
                    "default",
                    "unit",
                    "impact",
                }
            }
        sections[section_name] = fields
    return sections


@router.post("/validate-configuration")
def validate_configuration(
    config: BotConfiguration,
    _: User = Depends(get_current_user),
) -> dict:
    return jsonable_encoder(config.model_dump(mode="json"))


def profile_read(db: Session, row: StrategyProfile) -> StrategyProfileRead:
    count = db.scalar(
        select(func.count(Bot.id)).where(
            Bot.strategy_profile_id == row.id,
            Bot.archived_at.is_(None),
        )
    ) or 0
    return StrategyProfileRead.model_validate({**row.__dict__, "bot_count": count})


@profiles.get("", response_model=list[StrategyProfileRead])
def list_profiles(
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[StrategyProfileRead]:
    query = select(StrategyProfile)
    if not include_archived:
        query = query.where(StrategyProfile.status != "ARCHIVED")
    return [
        profile_read(db, row)
        for row in db.scalars(query.order_by(StrategyProfile.name))
    ]


@profiles.post("", response_model=StrategyProfileRead, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: StrategyProfileCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StrategyProfileRead:
    if db.scalar(select(StrategyProfile).where(StrategyProfile.name == payload.name)):
        raise HTTPException(status_code=409, detail="Strategy profile name already exists")
    row = StrategyProfile(
        name=payload.name,
        description=payload.description,
        status="ACTIVE",
        config=jsonable_encoder(payload.initial_config.model_dump(mode="json")),
    )
    db.add(row)
    db.flush()
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="STRATEGY_CREATED",
        target_type="STRATEGY_PROFILE",
        target_id=str(row.id),
    )
    db.commit()
    db.refresh(row)
    return profile_read(db, row)


@profiles.get("/{profile_id}", response_model=StrategyProfileRead)
def get_profile(
    profile_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StrategyProfileRead:
    row = db.get(StrategyProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy profile not found")
    return profile_read(db, row)


@profiles.patch("/{profile_id}", response_model=StrategyProfileRead)
def update_profile(
    profile_id: uuid.UUID,
    payload: StrategyProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StrategyProfileRead:
    row = db.get(StrategyProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy profile not found")
    if row.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail="Archived strategy cannot be edited")
    values = payload.model_dump(exclude_none=True)
    config = payload.config
    values.pop("config", None)
    if "name" in values:
        duplicate = db.scalar(
            select(StrategyProfile).where(
                StrategyProfile.name == values["name"],
                StrategyProfile.id != row.id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Strategy profile name already exists")
    for key, value in values.items():
        setattr(row, key, value)
    if config is not None:
        row.config = jsonable_encoder(config.model_dump(mode="json"))
        bots = db.scalars(
            select(Bot).where(
                Bot.strategy_profile_id == row.id,
                Bot.archived_at.is_(None),
            )
        )
        for bot in bots:
            if bot.market_feed_id is None:
                continue
            feed = db.get(MarketFeed, bot.market_feed_id)
            if feed is None:
                continue
            effective = effective_strategy_config(
                row, bot.config_overrides, symbol=feed.canonical_symbol
            )
            config_row = ConfigVersion(
                bot_id=bot.id,
                version=next_config_version(db, bot.id),
                status="ACTIVE",
                config=jsonable_encoder(effective.model_dump(mode="json")),
                strategy_profile_id=row.id,
                config_overrides=jsonable_encoder(bot.config_overrides),
                created_by=user.id,
            )
            db.add(config_row)
            db.flush()
            activate_config_version(db, bot, config_row)
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="STRATEGY_UPDATED",
        target_type="STRATEGY_PROFILE",
        target_id=str(row.id),
    )
    db.commit()
    db.refresh(row)
    return profile_read(db, row)


@profiles.delete("/{profile_id}", response_model=StrategyProfileRead)
def archive_profile(
    profile_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StrategyProfileRead:
    row = db.get(StrategyProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy profile not found")
    row.status = "ARCHIVED"
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="STRATEGY_ARCHIVED",
        target_type="STRATEGY_PROFILE",
        target_id=str(row.id),
    )
    db.commit()
    db.refresh(row)
    return profile_read(db, row)
