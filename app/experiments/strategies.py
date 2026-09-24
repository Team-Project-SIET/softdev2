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


class SimpleMultimodalStrategy:
    """Let SimpleAI plan rail, road, and air routes."""

    identifier = "simple-multimodal"
    version = "1"
    mode_parameters = {"use_trains": "1", "use_roadvehs": "1", "use_aircraft": "1"}

    def configure(self, scenario: ScenarioConfig) -> tuple[PlanningConfiguration, AIConfig]:
        return _simple_ai_configuration(self.identifier, self.version, self.mode_parameters)


class SimpleRoadOnlyStrategy:
    """Constrain the same SimpleAI planner to road vehicles."""

    identifier = "simple-road-only"
    version = "1"
    mode_parameters = {"use_trains": "0", "use_roadvehs": "1", "use_aircraft": "0"}

    def configure(self, scenario: ScenarioConfig) -> tuple[PlanningConfiguration, AIConfig]:
        return _simple_ai_configuration(self.identifier, self.version, self.mode_parameters)


def _simple_ai_configuration(
    identifier: str, version: str, parameters: dict[str, str]
) -> tuple[PlanningConfiguration, AIConfig]:
    ordered = tuple(sorted(parameters.items()))
    return (
        PlanningConfiguration(
            strategy_identifier=identifier,
            strategy_version=version,
            parameters=dict(ordered),
        ),
        AIConfig(
            content_id="534d504c",
            name="SimpleAI",
            md5="b3137bbd0c73641cf510ead06e36dab6",
            parameters=ordered,
        ),
    )


COMPARISON_STRATEGIES: dict[str, PlanningStrategy] = {
    "multimodal": SimpleMultimodalStrategy(),
    "road-only": SimpleRoadOnlyStrategy(),
}
