"""Content-addressed offline run history using the project's SQLAlchemy conventions."""

import json
from pathlib import Path

from sqlalchemy import Engine, String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database.base import Base
from app.experiments.freight_evaluation import FreightEvaluation, document_digest
from app.experiments.model import JSONDocument


class FreightRunRecord(Base):
    __tablename__ = "freight_run_history"

    source_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_digest: Mapped[str] = mapped_column(String(64))
    evaluation: Mapped[dict] = mapped_column(JSONDocument)


class FreightHistory:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine("sqlite+pysqlite:///" + str(path.resolve()))
        Base.metadata.tables[FreightRunRecord.__tablename__].create(self.engine, checkfirst=True)

    @classmethod
    def from_engine(cls, engine: Engine) -> FreightHistory:
        """Use a migrated SQLAlchemy database, including PostgreSQL; never migrate here."""
        history = cls.__new__(cls)
        history.engine = engine
        return history

    def add(self, evaluations: list[FreightEvaluation]) -> None:
        with Session(self.engine) as session, session.begin():
            for evaluation in evaluations:
                document = evaluation.model_dump(mode="json")
                # Keep pre-network history bytes stable when the optional report is absent.
                if document.get("network_report") is None:
                    document.pop("network_report", None)
                digest = document_digest(document)
                prior = session.get(FreightRunRecord, evaluation.history_key)
                if prior is not None:
                    if prior.evaluation_digest != digest:
                        raise ValueError(
                            "history source already exists with different provenance/evaluation"
                        )
                    continue
                session.add(
                    FreightRunRecord(
                        source_digest=evaluation.history_key,
                        evaluation_digest=digest,
                        evaluation=document,
                    )
                )

    def runs(self) -> tuple[FreightEvaluation, ...]:
        with Session(self.engine) as session:
            rows = session.scalars(select(FreightRunRecord)).all()
            for row in rows:
                if document_digest(row.evaluation) != row.evaluation_digest:
                    raise ValueError("stored freight evaluation digest mismatch")
            return tuple(
                sorted(
                    (
                        FreightEvaluation.model_validate_json(json.dumps(row.evaluation))
                        for row in rows
                    ),
                    key=lambda run: (run.attempt, run.run_name),
                )
            )

    def close(self):
        self.engine.dispose()
