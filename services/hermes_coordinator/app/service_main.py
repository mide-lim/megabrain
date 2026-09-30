"""Application factory and fail-closed entrypoint for the coordinator service."""
from __future__ import annotations

import argparse
import signal
import sys
import threading
from typing import Protocol

from .control_plane_client import ControlPlaneClient
from .coordinator_service import CoordinatorService, WorkSource
from .coordinator_turn import CoordinatorTurnRunner
from .hermes_oneshot import HermesOneShotRunner
from .provider_control_plane import ProviderObservationClient
from .provider_observer import HermesUsageProbe, ProviderObserver
from .production_capabilities import IdleWorkSource, ProductionCapabilityProvider
from .service_config import ConfigError, ServiceConfig, parse_service_config

CONFIG_ERROR_STATUS = "COORDINATOR_CONFIG_INVALID"
CONFIG_ERROR_EXIT_CODE = 2
CAPABILITY_BOOTSTRAP_STATUS = "PRODUCTION_CAPABILITY_BOOTSTRAP_UNAVAILABLE"
CAPABILITY_BOOTSTRAP_EXIT_CODE = 78


class CapabilityProvider(Protocol):
    """Binds externally obtained capabilities to externally selected work."""

    def bind(self, work_source: WorkSource) -> WorkSource: ...


class ServiceStartupError(RuntimeError):
    """Stable startup boundary; intentionally contains no configuration values."""


def build_coordinator_service(
    config: ServiceConfig,
    *,
    work_source: WorkSource,
    capability_provider: CapabilityProvider,
) -> CoordinatorService:
    """Wire the existing bounded runtime without selecting work or minting capability."""
    bound_work_source = capability_provider.bind(work_source)
    if not hasattr(bound_work_source, "next_work"):
        raise ServiceStartupError("invalid external work source")
    hermes_environment = {"HOME": str(config.hermes_home), "HERMES_HOME": str(config.hermes_home)}
    observer = ProviderObserver(
        probe=HermesUsageProbe(
            hermes_executable=config.hermes_executable,
            environment=hermes_environment,
        )
    )
    control_plane_client = ControlPlaneClient(config.control_plane_socket)
    observation_client = ProviderObservationClient(config.control_plane_socket)
    one_shot_runner = HermesOneShotRunner(
        config.runtime_directory,
        hermes_executable=config.hermes_executable,
        environment=hermes_environment,
        hermes_home=config.hermes_home,
    )
    turn_runner = CoordinatorTurnRunner(control_plane_client, one_shot_runner)
    return CoordinatorService(
        work_source=bound_work_source,
        provider_observer=observer,
        provider_observation_client=observation_client,
        turn_runner=turn_runner,
        idle_interval_seconds=config.idle_interval_seconds,
    )


def run_service(
    config: ServiceConfig,
    *,
    work_source: WorkSource,
    capability_provider: CapabilityProvider,
    stop_event: threading.Event | None = None,
) -> None:
    """Run a dependency-injected service for future capability-bootstrap integration."""
    service = build_coordinator_service(
        config,
        work_source=work_source,
        capability_provider=capability_provider,
    )
    install_stop_signal_handlers(service)
    service.run_forever(stop_event or threading.Event())


def install_stop_signal_handlers(service: CoordinatorService) -> None:
    """Request bounded shutdown only; service owns its normal shutdown sequence."""

    def request_stop(_signum: int, _frame: object) -> None:
        service.request_stop()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="megabrain-hermes-coordinator")
    parser.add_argument("--config", required=True)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = parse_service_config(args.config)
    except ConfigError:
        print(CONFIG_ERROR_STATUS, file=sys.stderr)
        return CONFIG_ERROR_EXIT_CODE
    if args.check_config:
        return 0
    try:
        run_service(
            config,
            work_source=IdleWorkSource(),
            capability_provider=ProductionCapabilityProvider(ControlPlaneClient(config.control_plane_socket)),
        )
    except RuntimeError:
        print(CAPABILITY_BOOTSTRAP_STATUS, file=sys.stderr)
        return CAPABILITY_BOOTSTRAP_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
