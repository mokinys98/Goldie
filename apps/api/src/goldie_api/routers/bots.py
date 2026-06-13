import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from goldie_domain.config import DEFAULT_BOT_CONFIGURATION, BotConfiguration
from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Bot, ConfigVersion, MarketFeed, PaperAccount, Run, Signal, User
from ..schemas import (
    BotCreate,
    BotRead,
    ConfigCreate,
    ConfigRead,
    MarketFeedAssignment,
    SignalRead,
)
from ..security import get_current_user
from ..services import add_audit, next_config_version

router = APIRouter(prefix="/api/v1", tags=["bots"])


def get_bot_or_404(db: Session, bot_id: uuid.UUID) -> Bot:
    bot = db.get(Bot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


@router.get("/bots", response_model=list[BotRead])
def list_bots(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Bot]:
    return list(db.scalars(select(Bot).order_by(Bot.created_at)))


@router.post("/bots", response_model=BotRead, status_code=status.HTTP_201_CREATED)
def create_bot(
    payload: BotCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Bot:
    existing = db.scalar(select(Bot).where(Bot.name == payload.name))
    if existing:
        raise HTTPException(status_code=409, detail="Bot name already exists")
    initial_config = payload.initial_config or BotConfiguration.model_validate(
        DEFAULT_BOT_CONFIGURATION
    )
    default_feed = db.scalar(
        select(MarketFeed)
        .where(
            MarketFeed.canonical_symbol == initial_config.market.symbol,
            MarketFeed.provider == "oanda",
        )
        .order_by(desc(MarketFeed.created_at))
    )
    bot = Bot(
        name=payload.name,
        description=payload.description,
        mode=payload.mode,
        market_feed_id=default_feed.id if default_feed else None,
    )
    db.add(bot)
    db.flush()
    if payload.mode == "PAPER":
        opening_balance = Decimal("10000")
        db.add(
            PaperAccount(
                bot_id=bot.id,
                currency="USD",
                initial_balance=opening_balance,
                balance=opening_balance,
                equity=opening_balance,
                available_cash=opening_balance,
            )
        )
    config = ConfigVersion(
        bot_id=bot.id,
        version=1,
        status="DRAFT",
        config=jsonable_encoder(
            initial_config.model_dump(mode="json")
        ),
        created_by=user.id,
    )
    db.add(config)
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="BOT_CREATED",
        target_type="BOT",
        target_id=str(bot.id),
    )
    db.commit()
    db.refresh(bot)
    return bot


@router.put("/bots/{bot_id}/market-feed", response_model=BotRead)
def assign_market_feed(
    bot_id: uuid.UUID,
    payload: MarketFeedAssignment,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Bot:
    bot = get_bot_or_404(db, bot_id)
    feed = db.get(MarketFeed, payload.market_feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Market feed not found")
    config_row = (
        db.get(ConfigVersion, bot.active_config_version_id)
        if bot.active_config_version_id
        else db.scalar(
            select(ConfigVersion)
            .where(ConfigVersion.bot_id == bot.id)
            .order_by(desc(ConfigVersion.version))
        )
    )
    if config_row:
        config = BotConfiguration.model_validate(config_row.config)
        if config.market.symbol != feed.canonical_symbol:
            raise HTTPException(
                status_code=409,
                detail="Market feed symbol does not match bot configuration",
            )
    bot.market_feed_id = feed.id
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="MARKET_FEED_ASSIGNED",
        target_type="BOT",
        target_id=str(bot.id),
        details={"market_feed_id": str(feed.id)},
    )
    db.commit()
    db.refresh(bot)
    return bot


@router.get("/bots/{bot_id}", response_model=BotRead)
def get_bot(
    bot_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Bot:
    return get_bot_or_404(db, bot_id)


@router.get("/bots/{bot_id}/config-versions", response_model=list[ConfigRead])
def list_config_versions(
    bot_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ConfigVersion]:
    get_bot_or_404(db, bot_id)
    return list(
        db.scalars(
            select(ConfigVersion)
            .where(ConfigVersion.bot_id == bot_id)
            .order_by(desc(ConfigVersion.version))
        )
    )


@router.post(
    "/bots/{bot_id}/config-versions",
    response_model=ConfigRead,
    status_code=status.HTTP_201_CREATED,
)
def create_config_version(
    bot_id: uuid.UUID,
    payload: ConfigCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConfigVersion:
    get_bot_or_404(db, bot_id)
    row = ConfigVersion(
        bot_id=bot_id,
        version=next_config_version(db, bot_id),
        status="DRAFT",
        config=jsonable_encoder(payload.config.model_dump(mode="json")),
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="CONFIG_VERSION_CREATED",
        target_type="CONFIG_VERSION",
        target_id=str(row.id),
        details={"bot_id": str(bot_id), "version": row.version},
    )
    db.commit()
    db.refresh(row)
    return row


@router.post("/config-versions/{config_id}/validate", response_model=ConfigRead)
def validate_config(
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConfigVersion:
    row = db.get(ConfigVersion, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Config version not found")
    if row.status not in {"DRAFT", "VALIDATED"}:
        raise HTTPException(status_code=409, detail="Only draft config can be validated")
    try:
        validated = BotConfiguration.model_validate(row.config)
        row.config = jsonable_encoder(validated.model_dump(mode="json"))
        row.validation_errors = None
        row.status = "VALIDATED"
    except ValidationError as exc:
        row.validation_errors = jsonable_encoder(exc.errors())
        row.status = "DRAFT"
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="CONFIG_VALIDATED",
        target_type="CONFIG_VERSION",
        target_id=str(row.id),
        details={"valid": row.status == "VALIDATED"},
    )
    db.commit()
    db.refresh(row)
    return row


@router.post("/config-versions/{config_id}/activate", response_model=ConfigRead)
def activate_config(
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConfigVersion:
    row = db.get(ConfigVersion, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Config version not found")
    if row.status != "VALIDATED":
        raise HTTPException(status_code=409, detail="Config must be validated first")
    bot = get_bot_or_404(db, row.bot_id)
    previous = db.scalar(
        select(ConfigVersion).where(
            ConfigVersion.bot_id == bot.id, ConfigVersion.status == "ACTIVE"
        )
    )
    now = datetime.now(UTC)
    if previous:
        previous.status = "SUPERSEDED"
    for run in db.scalars(select(Run).where(Run.bot_id == bot.id, Run.status == "ACTIVE")):
        run.status = "SUPERSEDED"
        run.ended_at = now
    row.status = "ACTIVE"
    row.activated_at = now
    bot.active_config_version_id = row.id
    bot.state = "MONITORING"
    run = Run(bot_id=bot.id, config_version_id=row.id, mode=bot.mode)
    db.add(run)
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="CONFIG_ACTIVATED",
        target_type="CONFIG_VERSION",
        target_id=str(row.id),
        details={"bot_id": str(bot.id)},
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/bots/{bot_id}/runs")
def list_runs(
    bot_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    get_bot_or_404(db, bot_id)
    rows = db.scalars(select(Run).where(Run.bot_id == bot_id).order_by(desc(Run.created_at)))
    return [
        {
            "id": str(row.id),
            "config_version_id": str(row.config_version_id),
            "mode": row.mode,
            "status": row.status,
            "created_at": row.created_at,
            "ended_at": row.ended_at,
        }
        for row in rows
    ]


@router.get("/bots/{bot_id}/signals", response_model=list[SignalRead])
def list_signals(
    bot_id: uuid.UUID,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Signal]:
    get_bot_or_404(db, bot_id)
    return list(
        db.scalars(
            select(Signal)
            .where(Signal.bot_id == bot_id)
            .order_by(desc(Signal.observed_at))
            .limit(min(max(limit, 1), 500))
        )
    )
