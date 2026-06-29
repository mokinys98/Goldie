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
from ..models import (
    Bot,
    ConfigVersion,
    MarketFeed,
    PaperAccount,
    Run,
    Signal,
    SignalOutcome,
    StrategyProfile,
    User,
)
from ..schemas import (
    BotApplyStrategy,
    BotCreate,
    BotOverridesUpdate,
    BotRead,
    BotUpdate,
    BulkBotCreate,
    BulkBotResult,
    ConfigCreate,
    ConfigRead,
    MarketFeedAssignment,
    SignalRead,
)
from ..security import get_current_user
from ..services import (
    activate_config_version,
    add_audit,
    effective_strategy_config,
    next_config_version,
)

router = APIRouter(prefix="/api/v1", tags=["bots"])


def get_bot_or_404(db: Session, bot_id: uuid.UUID) -> Bot:
    bot = db.get(Bot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


def ensure_config_matches_feed(
    db: Session,
    bot: Bot,
    config: BotConfiguration,
) -> None:
    if bot.market_feed_id is None:
        return
    feed = db.get(MarketFeed, bot.market_feed_id)
    if feed is not None and config.market.symbol != feed.canonical_symbol:
        raise HTTPException(
            status_code=409,
            detail="Configuration symbol does not match the assigned market feed",
        )


@router.get("/bots", response_model=list[BotRead])
def list_bots(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Bot]:
    return list(
        db.scalars(
            select(Bot).where(Bot.archived_at.is_(None)).order_by(Bot.created_at)
        )
    )


@router.post("/bots", response_model=BotRead, status_code=status.HTTP_201_CREATED)
def create_bot(
    payload: BotCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Bot:
    existing = db.scalar(select(Bot).where(Bot.name == payload.name))
    if existing:
        raise HTTPException(status_code=409, detail="Bot name already exists")
    selected_feed = (
        db.get(MarketFeed, payload.market_feed_id)
        if payload.market_feed_id is not None
        else None
    )
    if payload.market_feed_id is not None and selected_feed is None:
        raise HTTPException(status_code=404, detail="Market feed not found")
    profile = (
        db.get(StrategyProfile, payload.strategy_profile_id)
        if payload.strategy_profile_id is not None
        else None
    )
    if payload.strategy_profile_id is not None and (
        profile is None or profile.status == "ARCHIVED"
    ):
        raise HTTPException(status_code=404, detail="Active strategy not found")
    if profile is not None:
        profile_symbol = (profile.config.get("market") or {}).get("symbol", "XAUUSD")
        initial_config = effective_strategy_config(
            profile,
            {},
            symbol=selected_feed.canonical_symbol if selected_feed else profile_symbol,
        )
    else:
        initial_config = payload.initial_config or BotConfiguration.model_validate(
            DEFAULT_BOT_CONFIGURATION
        )
    if selected_feed is not None and profile is None:
        initial_config = initial_config.model_copy(
            update={
                "market": initial_config.market.model_copy(
                    update={"symbol": selected_feed.canonical_symbol}
                )
            }
        )
    elif selected_feed is None:
        selected_feed = db.scalar(
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
        market_feed_id=selected_feed.id if selected_feed else None,
        strategy_profile_id=profile.id if profile else None,
        config_overrides={},
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
        status="ACTIVE" if selected_feed else "DRAFT",
        config=jsonable_encoder(
            initial_config.model_dump(mode="json")
        ),
        strategy_profile_id=profile.id if profile else None,
        config_overrides={},
        created_by=user.id,
    )
    db.add(config)
    db.flush()
    if selected_feed:
        activate_config_version(db, bot, config)
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


@router.patch("/bots/{bot_id}", response_model=BotRead)
def update_bot(
    bot_id: uuid.UUID,
    payload: BotUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Bot:
    bot = get_bot_or_404(db, bot_id)
    if bot.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived bot cannot be edited")
    values = payload.model_dump(exclude_none=True)
    if "name" in values:
        duplicate = db.scalar(
            select(Bot).where(Bot.name == values["name"], Bot.id != bot.id)
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Bot name already exists")
    old_mode = bot.mode
    for key, value in values.items():
        setattr(bot, key, value)
    if old_mode != bot.mode and bot.mode == "PAPER":
        existing_account = db.scalar(
            select(PaperAccount).where(PaperAccount.bot_id == bot.id)
        )
        if existing_account is None:
            create_paper_account(db, bot)
    if old_mode != bot.mode and bot.active_config_version_id is not None:
        active_config = db.get(ConfigVersion, bot.active_config_version_id)
        if active_config is not None:
            activate_config_version(db, bot, active_config)
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="BOT_UPDATED",
        target_type="BOT",
        target_id=str(bot.id),
    )
    db.commit()
    db.refresh(bot)
    return bot


@router.delete("/bots/{bot_id}", response_model=BotRead)
def archive_bot(
    bot_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Bot:
    bot = get_bot_or_404(db, bot_id)
    now = datetime.now(UTC)
    bot.archived_at = now
    bot.state = "STOPPED"
    for run in db.scalars(
        select(Run).where(Run.bot_id == bot.id, Run.status == "ACTIVE")
    ):
        run.status = "SUPERSEDED"
        run.ended_at = now
    for outcome in db.scalars(
        select(SignalOutcome).where(
            SignalOutcome.bot_id == bot.id,
            SignalOutcome.status == "OPEN",
        )
    ):
        outcome.status = "CANCELLED"
        outcome.close_reason = "BOT_ARCHIVED"
        outcome.closed_at = now
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="BOT_ARCHIVED",
        target_type="BOT",
        target_id=str(bot.id),
    )
    db.commit()
    db.refresh(bot)
    return bot


def create_paper_account(db: Session, bot: Bot) -> None:
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


@router.post("/bots/bulk", response_model=list[BulkBotResult])
def create_bots_bulk(
    payload: BulkBotCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BulkBotResult]:
    profile = db.get(StrategyProfile, payload.strategy_profile_id)
    if profile is None or profile.status == "ARCHIVED":
        raise HTTPException(status_code=404, detail="Active strategy not found")
    results: list[BulkBotResult] = []
    for feed_id in dict.fromkeys(payload.market_feed_ids):
        feed = db.get(MarketFeed, feed_id)
        if feed is None:
            results.append(
                BulkBotResult(
                    market_feed_id=feed_id,
                    name="",
                    status="FAILED",
                    error="Market feed not found",
                )
            )
            continue
        values = {
            "symbol": feed.canonical_symbol,
            "strategy": profile.name.lower().replace(" ", "-"),
            "mode": payload.mode.lower(),
        }
        try:
            name = payload.name_template.format(**values)
        except (KeyError, ValueError):
            name = ""
        if not 2 <= len(name) <= 120:
            results.append(
                BulkBotResult(
                    market_feed_id=feed.id,
                    name=name,
                    status="FAILED",
                    error="Generated bot name must contain 2-120 characters",
                )
            )
            continue
        existing = db.scalar(select(Bot).where(Bot.name == name))
        if existing:
            results.append(
                BulkBotResult(
                    market_feed_id=feed.id,
                    name=name,
                    status="EXISTS",
                    bot=BotRead.model_validate(existing),
                )
            )
            continue
        config = effective_strategy_config(profile, {}, symbol=feed.canonical_symbol)
        bot = Bot(
            name=name,
            description=payload.description,
            mode=payload.mode,
            market_feed_id=feed.id,
            strategy_profile_id=profile.id,
            config_overrides={},
        )
        db.add(bot)
        db.flush()
        if payload.mode == "PAPER":
            create_paper_account(db, bot)
        config_row = ConfigVersion(
            bot_id=bot.id,
            version=1,
            status="ACTIVE",
            config=jsonable_encoder(config.model_dump(mode="json")),
            strategy_profile_id=profile.id,
            config_overrides={},
            created_by=user.id,
        )
        db.add(config_row)
        db.flush()
        activate_config_version(db, bot, config_row)
        add_audit(
            db,
            actor_type="USER",
            actor_id=str(user.id),
            action="BOT_BULK_CREATED",
            target_type="BOT",
            target_id=str(bot.id),
            details={"request_id": str(payload.request_id), "market_feed_id": str(feed.id)},
        )
        db.commit()
        db.refresh(bot)
        results.append(
            BulkBotResult(
                market_feed_id=feed.id,
                name=name,
                status="CREATED",
                bot=BotRead.model_validate(bot),
            )
        )
    return results


@router.post("/bots/{bot_id}/apply-strategy", response_model=ConfigRead)
def apply_strategy(
    bot_id: uuid.UUID,
    payload: BotApplyStrategy,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConfigVersion:
    bot = get_bot_or_404(db, bot_id)
    profile = db.get(StrategyProfile, payload.strategy_profile_id)
    if profile is None or profile.status == "ARCHIVED":
        raise HTTPException(status_code=404, detail="Active strategy not found")
    if bot.market_feed_id is None:
        raise HTTPException(status_code=409, detail="Bot must have an assigned market feed")
    feed = db.get(MarketFeed, bot.market_feed_id)
    assert feed is not None
    config = effective_strategy_config(profile, {}, symbol=feed.canonical_symbol)
    bot.strategy_profile_id = profile.id
    bot.config_overrides = {}
    row = ConfigVersion(
        bot_id=bot.id,
        version=next_config_version(db, bot.id),
        status="ACTIVE",
        config=jsonable_encoder(config.model_dump(mode="json")),
        strategy_profile_id=profile.id,
        config_overrides={},
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    activate_config_version(db, bot, row)
    add_audit(
        db, actor_type="USER", actor_id=str(user.id), action="STRATEGY_APPLIED",
        target_type="BOT", target_id=str(bot.id),
        details={"strategy_profile_id": str(profile.id)},
    )
    db.commit()
    db.refresh(row)
    return row


@router.put("/bots/{bot_id}/overrides", response_model=ConfigRead)
def update_overrides(
    bot_id: uuid.UUID,
    payload: BotOverridesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConfigVersion:
    bot = get_bot_or_404(db, bot_id)
    if bot.strategy_profile_id is None:
        raise HTTPException(status_code=409, detail="Bot is not linked to a strategy")
    if "market" in payload.overrides:
        raise HTTPException(status_code=409, detail="Market settings cannot be overridden")
    if bot.market_feed_id is None:
        raise HTTPException(status_code=409, detail="Bot must have an assigned market feed")
    profile = db.get(StrategyProfile, bot.strategy_profile_id)
    feed = db.get(MarketFeed, bot.market_feed_id)
    assert profile is not None and feed is not None
    config = effective_strategy_config(profile, payload.overrides, symbol=feed.canonical_symbol)
    bot.config_overrides = jsonable_encoder(payload.overrides)
    row = ConfigVersion(
        bot_id=bot.id,
        version=next_config_version(db, bot.id),
        status="ACTIVE",
        config=jsonable_encoder(config.model_dump(mode="json")),
        strategy_profile_id=profile.id,
        config_overrides=jsonable_encoder(payload.overrides),
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    activate_config_version(db, bot, row)
    add_audit(
        db, actor_type="USER", actor_id=str(user.id), action="BOT_OVERRIDES_UPDATED",
        target_type="BOT", target_id=str(bot.id),
        details={"overrides": payload.overrides},
    )
    db.commit()
    db.refresh(row)
    return row


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
    bot = get_bot_or_404(db, bot_id)
    ensure_config_matches_feed(db, bot, payload.config)
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
    ensure_config_matches_feed(
        db,
        bot,
        BotConfiguration.model_validate(row.config),
    )
    activate_config_version(db, bot, row)
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
