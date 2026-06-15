import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from goldie_domain import BotConfiguration, strategy_catalog
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Bot, StrategyProfile, StrategyVersion, User
from ..schemas import (
    StrategyProfileCreate,
    StrategyProfileRead,
    StrategyProfileUpdate,
    StrategyVersionCreate,
    StrategyVersionRead,
)
from ..security import get_current_user
from ..services import add_audit

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])
profiles = APIRouter(prefix="/api/v1/strategy-profiles", tags=["strategy-profiles"])
versions = APIRouter(prefix="/api/v1/strategy-versions", tags=["strategy-profiles"])


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
    published = (
        db.get(StrategyVersion, row.current_published_version_id)
        if row.current_published_version_id
        else None
    )
    count = db.scalar(
        select(func.count(Bot.id))
        .join(StrategyVersion, Bot.strategy_version_id == StrategyVersion.id)
        .where(StrategyVersion.strategy_profile_id == row.id)
    ) or 0
    return StrategyProfileRead.model_validate(
        {
            **row.__dict__,
            "bot_count": count,
            "published_version": published,
        }
    )


@profiles.get("", response_model=list[StrategyProfileRead])
def list_profiles(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[StrategyProfileRead]:
    return [
        profile_read(db, row)
        for row in db.scalars(select(StrategyProfile).order_by(StrategyProfile.name))
    ]


@profiles.post("", response_model=StrategyProfileRead, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: StrategyProfileCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StrategyProfileRead:
    if db.scalar(select(StrategyProfile).where(StrategyProfile.name == payload.name)):
        raise HTTPException(status_code=409, detail="Strategy profile name already exists")
    row = StrategyProfile(name=payload.name, description=payload.description)
    db.add(row)
    db.flush()
    version = StrategyVersion(
        strategy_profile_id=row.id,
        version=1,
        status="DRAFT",
        config=jsonable_encoder(payload.initial_config.model_dump(mode="json")),
        created_by=user.id,
    )
    db.add(version)
    add_audit(
        db, actor_type="USER", actor_id=str(user.id), action="STRATEGY_CREATED",
        target_type="STRATEGY_PROFILE", target_id=str(row.id),
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
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    add_audit(
        db, actor_type="USER", actor_id=str(user.id), action="STRATEGY_UPDATED",
        target_type="STRATEGY_PROFILE", target_id=str(row.id),
    )
    db.commit()
    db.refresh(row)
    return profile_read(db, row)


@profiles.get("/{profile_id}/versions", response_model=list[StrategyVersionRead])
def list_versions(
    profile_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[StrategyVersion]:
    if db.get(StrategyProfile, profile_id) is None:
        raise HTTPException(status_code=404, detail="Strategy profile not found")
    return list(
        db.scalars(
            select(StrategyVersion)
            .where(StrategyVersion.strategy_profile_id == profile_id)
            .order_by(StrategyVersion.version.desc())
        )
    )


@versions.get("/{version_id}", response_model=StrategyVersionRead)
def get_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StrategyVersion:
    row = db.get(StrategyVersion, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy version not found")
    return row


@profiles.post(
    "/{profile_id}/versions",
    response_model=StrategyVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_version(
    profile_id: uuid.UUID,
    payload: StrategyVersionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StrategyVersion:
    if db.get(StrategyProfile, profile_id) is None:
        raise HTTPException(status_code=404, detail="Strategy profile not found")
    latest = db.scalar(
        select(func.max(StrategyVersion.version)).where(
            StrategyVersion.strategy_profile_id == profile_id
        )
    )
    row = StrategyVersion(
        strategy_profile_id=profile_id,
        version=(latest or 0) + 1,
        status="DRAFT",
        config=jsonable_encoder(payload.config.model_dump(mode="json")),
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@versions.post("/{version_id}/validate", response_model=StrategyVersionRead)
def validate_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StrategyVersion:
    row = db.get(StrategyVersion, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy version not found")
    if row.status not in {"DRAFT", "VALIDATED"}:
        raise HTTPException(status_code=409, detail="Published versions are immutable")
    try:
        config = BotConfiguration.model_validate(row.config)
        row.config = jsonable_encoder(config.model_dump(mode="json"))
        row.validation_errors = None
        row.status = "VALIDATED"
    except ValidationError as exc:
        row.validation_errors = jsonable_encoder(exc.errors())
        row.status = "DRAFT"
    db.commit()
    db.refresh(row)
    return row


@versions.post("/{version_id}/publish", response_model=StrategyVersionRead)
def publish_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StrategyVersion:
    row = db.get(StrategyVersion, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy version not found")
    if row.status != "VALIDATED":
        raise HTTPException(status_code=409, detail="Strategy version must be validated")
    metadata = next(
        (
            item
            for item in strategy_catalog()
            if item["name"] == row.config.get("strategy", {}).get("name")
        ),
        None,
    )
    if metadata is None or any(
        not field.get("description") or not field.get("unit") or not field.get("impact")
        for field in metadata["parameters"].values()
    ):
        raise HTTPException(
            status_code=409,
            detail="Every strategy parameter must have description, unit and impact metadata",
        )
    profile = db.get(StrategyProfile, row.strategy_profile_id)
    assert profile is not None
    previous = (
        db.get(StrategyVersion, profile.current_published_version_id)
        if profile.current_published_version_id
        else None
    )
    if previous:
        previous.status = "ARCHIVED"
    row.status = "PUBLISHED"
    row.published_at = datetime.now(UTC)
    profile.current_published_version_id = row.id
    profile.status = "ACTIVE"
    add_audit(
        db, actor_type="USER", actor_id=str(user.id), action="STRATEGY_PUBLISHED",
        target_type="STRATEGY_VERSION", target_id=str(row.id),
    )
    db.commit()
    db.refresh(row)
    return row
