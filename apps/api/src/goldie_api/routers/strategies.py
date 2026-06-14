from fastapi import APIRouter, Depends
from goldie_domain import strategy_catalog

from ..models import User
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


@router.get("")
def list_strategies(_: User = Depends(get_current_user)) -> list[dict]:
    return strategy_catalog()
