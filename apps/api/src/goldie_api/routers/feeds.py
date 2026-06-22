import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..dependencies import require_agent_token
from ..ingestion import process_candle_batch, process_quote_batch
from ..models import (
    Agent,
    Bot,
    Candle,
    InstrumentSpecification,
    MarketFeed,
    User,
)
from ..schemas import (
    FeedCandleBatch,
    FeedHeartbeatRequest,
    FeedQuoteBatch,
    InstrumentSpecificationIn,
    MarketFeedRead,
    MarketFeedRegister,
    MarketFeedRegistration,
)
from ..security import get_current_user
from ..realtime import invalidate_collector_overview, publish_event, publish_event_sync
from ..settings import get_settings

router = APIRouter(prefix="/api/v1/market-feeds", tags=["market-feeds"])
_ingestion_semaphore = asyncio.Semaphore(get_settings().ingestion_concurrency)


def get_feed_or_404(db: Session, feed_id: uuid.UUID) -> MarketFeed:
    feed = db.get(MarketFeed, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Market feed not found")
    return feed


def validate_feed_agent(db: Session, feed_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.market_feed_id != feed_id:
        raise HTTPException(status_code=403, detail="Agent and market feed do not match")
    return agent


def broadcast_to_feed_bots(
    db: Session,
    feed_id: uuid.UUID,
    payload: dict,
) -> None:
    bot_ids = list(
        db.scalars(select(Bot.id).where(Bot.market_feed_id == feed_id))
    )
    if not bot_ids:
        publish_event_sync(payload)
        return
    for bot_id in bot_ids:
        publish_event_sync({**payload, "bot_instance_id": str(bot_id)})


@router.get("", response_model=list[MarketFeedRead])
def list_market_feeds(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[MarketFeed]:
    return list(db.scalars(select(MarketFeed).order_by(MarketFeed.created_at)))


@router.post(
    "/register",
    response_model=MarketFeedRegistration,
    status_code=status.HTTP_201_CREATED,
)
def register_market_feed(
    payload: MarketFeedRegister,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> MarketFeedRegistration:
    feed = db.scalar(
        select(MarketFeed).where(
            MarketFeed.provider == payload.provider,
            MarketFeed.environment == payload.environment,
            MarketFeed.provider_symbol == payload.provider_symbol,
        )
    )
    if feed is None:
        feed = MarketFeed(
            provider=payload.provider,
            environment=payload.environment,
            canonical_symbol=payload.canonical_symbol,
            provider_symbol=payload.provider_symbol,
            details=payload.details,
        )
        db.add(feed)
        db.flush()
    else:
        feed.canonical_symbol = payload.canonical_symbol
        feed.details = payload.details

    agent = db.scalar(
        select(Agent)
        .where(
            Agent.market_feed_id == feed.id,
            Agent.adapter == payload.provider,
            Agent.name == payload.agent_name,
        )
        .order_by(desc(Agent.created_at))
    )
    if agent is None:
        agent = Agent(
            market_feed_id=feed.id,
            name=payload.agent_name,
            adapter=payload.provider,
            status="REGISTERED",
            details={"read_only": True},
        )
        db.add(agent)
    db.commit()
    db.refresh(feed)
    invalidate_collector_overview()
    db.refresh(agent)
    latest_candle = db.scalar(
        select(Candle.opened_at)
        .where(Candle.market_feed_id == feed.id, Candle.is_complete.is_(True))
        .order_by(desc(Candle.opened_at))
    )
    return MarketFeedRegistration(
        feed=feed,
        agent=agent,
        latest_candle_at=latest_candle,
    )


@router.post("/{feed_id}/heartbeat", response_model=MarketFeedRead)
def heartbeat(
    feed_id: uuid.UUID,
    payload: FeedHeartbeatRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> MarketFeed:
    feed = get_feed_or_404(db, feed_id)
    agent = validate_feed_agent(db, feed_id, payload.agent_id)
    observed_at = payload.observed_at.astimezone(UTC)
    feed.status = payload.status
    feed.details = payload.details
    feed.last_heartbeat_at = observed_at
    agent.status = payload.status
    agent.details = payload.details
    agent.last_heartbeat_at = observed_at
    db.commit()
    db.refresh(feed)
    invalidate_collector_overview()
    broadcast_to_feed_bots(
        db,
        feed.id,
        {
            "event_type": "market_feed.heartbeat",
            "occurred_at": datetime.now(UTC).isoformat(),
            "market_feed_id": str(feed.id),
            "status": feed.status,
        }
    )
    return feed


@router.post("/{feed_id}/instrument-specification", status_code=202)
def ingest_instrument_specification(
    feed_id: uuid.UUID,
    payload: InstrumentSpecificationIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> dict:
    feed = get_feed_or_404(db, feed_id)
    validate_feed_agent(db, feed_id, payload.agent_id)
    if payload.provider_symbol != feed.provider_symbol:
        raise HTTPException(status_code=422, detail="Provider symbol does not match feed")
    point = Decimal(10) ** payload.pip_location
    row = db.scalar(
        select(InstrumentSpecification)
        .where(InstrumentSpecification.market_feed_id == feed_id)
        .order_by(desc(InstrumentSpecification.updated_at))
    )
    values = payload.model_dump(exclude={"agent_id"})
    if row is None:
        row = InstrumentSpecification(
            market_feed_id=feed_id,
            agent_id=payload.agent_id,
            point=point,
            source=feed.provider,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
        row.agent_id = payload.agent_id
        row.point = point
        row.source = feed.provider
    db.commit()
    broadcast_to_feed_bots(
        db,
        feed.id,
        {
            "event_type": "instrument.specification",
            "occurred_at": datetime.now(UTC).isoformat(),
            "market_feed_id": str(feed.id),
            "symbol": feed.canonical_symbol,
        }
    )
    return {"accepted": True}


@router.post("/{feed_id}/quotes/batch", status_code=202)
async def ingest_quotes(
    feed_id: uuid.UUID,
    payload: FeedQuoteBatch,
    _: None = Depends(require_agent_token),
) -> dict:
    async with _ingestion_semaphore:
        result, event = await asyncio.to_thread(process_quote_batch, feed_id, payload)
    if event:
        await publish_event(event)
    return result


@router.post("/{feed_id}/candles/batch", status_code=202)
async def ingest_candles(
    feed_id: uuid.UUID,
    payload: FeedCandleBatch,
    _: None = Depends(require_agent_token),
) -> dict:
    async with _ingestion_semaphore:
        result, event = await asyncio.to_thread(process_candle_batch, feed_id, payload)
    if event:
        await publish_event(event)
    return result
