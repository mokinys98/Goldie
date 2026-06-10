import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Agent, Bot
from ..schemas import AgentRead, AgentRegister, HeartbeatRequest
from ..services import add_audit
from ..settings import get_settings
from ..websocket import manager

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def require_agent_token(x_agent_token: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_agent_token, get_settings().agent_service_token):
        raise HTTPException(status_code=401, detail="Invalid agent token")


def get_agent_or_404(db: Session, agent_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/register", response_model=AgentRead)
def register_agent(
    payload: AgentRegister,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> Agent:
    if db.get(Bot, payload.bot_id) is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    agent = Agent(
        bot_id=payload.bot_id,
        name=payload.name,
        adapter=payload.adapter,
        details=payload.details,
        status="REGISTERED",
    )
    db.add(agent)
    db.flush()
    add_audit(
        db,
        actor_type="AGENT",
        actor_id=str(agent.id),
        action="AGENT_REGISTERED",
        target_type="BOT",
        target_id=str(payload.bot_id),
        details={"adapter": payload.adapter},
    )
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/{agent_id}/heartbeat", response_model=AgentRead)
async def heartbeat(
    agent_id: uuid.UUID,
    payload: HeartbeatRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> Agent:
    agent = get_agent_or_404(db, agent_id)
    agent.status = payload.status
    agent.details = payload.details
    agent.last_heartbeat_at = payload.observed_at.astimezone(UTC)
    db.commit()
    db.refresh(agent)
    await manager.broadcast(
        {
            "event_type": "agent.heartbeat",
            "occurred_at": datetime.now(UTC).isoformat(),
            "bot_instance_id": str(agent.bot_id),
            "agent_id": str(agent.id),
            "status": agent.status,
        }
    )
    return agent
