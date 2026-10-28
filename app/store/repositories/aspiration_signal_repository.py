"""Aspiration signals: where a student's own words say they're heading (s13 §4.3, data-model).

Saved after the reply, in its own short transaction, once per turn: a retried task can't
double-count. If the user was deleted meanwhile, nothing is saved.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.core.logging import get_logger
from app.domain.models.aspiration import AspirationSignals, ExtractAspiration
from app.store.tables import aspiration_signals

logger = get_logger(__name__)


class AspirationSignalRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(
        self, task: ExtractAspiration, signals: AspirationSignals, prompt_version: str
    ) -> bool:
        """False when the turn or student no longer exists (deleted before this ran)."""
        statement = (
            insert(aspiration_signals)
            .values(
                turn_id=task.turn_id,
                learner_id=task.learner_id,
                fields=[field.value for field in signals.fields],
                specificity=signals.specificity,
                constraints=[constraint.value for constraint in signals.constraints],
                sentiment=signals.sentiment.value,
                prompt_version=prompt_version,
            )
            .on_conflict_do_nothing(index_elements=["turn_id"])
        )
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(statement)
        except IntegrityError as exc:  # a foreign key: the user (and turn and learner) is gone
            logger.warning("aspiration_signals_user_gone", turn_id=str(task.turn_id), exc_info=exc)
            return False
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not save aspiration signals: {type(exc).__name__}") from exc
        return True
