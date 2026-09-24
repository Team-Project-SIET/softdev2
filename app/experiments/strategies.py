"""Planning policies select an OpenTTD AI and its experiment parameters."""

from typing import Protocol

from app.experiments.domain import AIConfig, PlanningConfiguration, ScenarioConfig


class PlanningStrategy(Protocol):
    identifier: str
    version: str

    def configure(self, scenario: ScenarioConfig) -> tuple[PlanningConfiguration, AIConfig]: ...


class BaselineStrategy:
    """Pinned trAIns baseline; future policies can supply different AI parameters."""

    identifier = "trains-baseline"
    version = "1"

    def configure(self, scenario: ScenarioConfig) -> tuple[PlanningConfiguration, AIConfig]:
        return (
            PlanningConfiguration(
                strategy_identifier=self.identifier,
                strategy_version=self.version,
                parameters={"ai": "trAIns 2.1", "scenario": scenario.identifier},
            ),
            AIConfig(
                content_id="54524149",
                name="trAIns",
                md5="c4c069dc797674e545411b59867ad0c2",
            ),
        )
