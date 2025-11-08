"""Main orchestrator for Harbor OIDC investigation."""

import asyncio
from datetime import datetime
import logging
from pathlib import Path
from typing import Optional

from .collectors.api import APICollector
from .collectors.database import DatabaseCollector
from .collectors.diagnostics import DiagnosticsCollector
from .collectors.k8s_resources import K8sResourceCollector
from .collectors.logs import LogCollector
from .config import (
    AUTHENTIK_NAMESPACE,
    AUTHENTIK_SERVER,
    AUTHENTIK_WORKER,
    HARBOR_CORE,
    HARBOR_JOBSERVICE,
    HARBOR_NAMESPACE,
    HARBOR_PORTAL,
    HARBOR_REGISTRY,
    IS_PROD,
)
from .k8s_client import K8sClient
from .testing.oidc_e2e import OIDCTester
from .utils.commands import CommandRunner
from .utils.file_writer import FileWriter


class ScientistMode:
    """Main orchestrator for comprehensive data collection."""

    def __init__(self, output_dir: Optional[str] = None):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.base_dir = (
            Path(output_dir)
            if output_dir
            else Path(f"observations/harbor-collection-{timestamp}")
        )
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(self.base_dir / "scientist_mode.log"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger(__name__)

        # Show which environment we're targeting
        env_mode = "production" if IS_PROD else "test"
        self.logger.info(f"Starting collection in {env_mode} environment")
        self.logger.info(f"Output directory: {self.base_dir}")
        self.logger.info(
            f"Targeting namespaces: harbor={HARBOR_NAMESPACE}, authentik={AUTHENTIK_NAMESPACE}"
        )

        # Create subdirectories
        self.dirs = {
            "logs": self.base_dir / "logs",
            "configs": self.base_dir / "configs",
            "k8s": self.base_dir / "k8s",
            "databases": self.base_dir / "databases",
            "source": self.base_dir / "source",
            "network": self.base_dir / "network",
            "api_tests": self.base_dir / "api_tests",
            "diagnostics": self.base_dir / "diagnostics",
            "e2e": self.base_dir / "e2e",
            "versions": self.base_dir / "versions",
        }

        for dir_path in self.dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.k8s = K8sClient(self.logger)
        self.file_writer = FileWriter(self.base_dir, self.logger)
        self.command_runner = CommandRunner(self.k8s, self.file_writer, self.logger)

        # Initialize collectors
        self.log_collector = LogCollector(self.k8s, self.file_writer, self.logger)
        self.k8s_collector = K8sResourceCollector(
            self.k8s, self.file_writer, self.logger
        )
        self.db_collector = DatabaseCollector(self.k8s, self.file_writer, self.logger)
        self.api_collector = APICollector(self.k8s, self.file_writer, self.logger)
        self.diagnostics_collector = DiagnosticsCollector(
            self.k8s, self.file_writer, self.logger
        )
        self.oidc_tester = OIDCTester(self.k8s, self.file_writer, self.logger)

    async def enable_observability(self) -> None:
        """Enable maximum observability on all components."""
        self.logger.info("Enabling debug logging on all components")

        # Harbor components - try multiple env vars for different versions
        harbor_debug = {
            HARBOR_CORE: {"LOG_LEVEL": "debug", "CORE_LOG_LEVEL": "debug"},
            HARBOR_PORTAL: {"LOG_LEVEL": "debug"},
            HARBOR_JOBSERVICE: {
                "CORE_LOG_LEVEL": "DEBUG",
                "JOBSERVICE_LOG_LEVEL": "DEBUG",
            },
            HARBOR_REGISTRY: {"LOG_LEVEL": "debug", "REGISTRY_LOG_LEVEL": "debug"},
            "harbor-registryctl": {"LOG_LEVEL": "debug"},
        }
        self._enable_debug_for_deployments(HARBOR_NAMESPACE, harbor_debug)

        # Try trace level for harbor-core if supported
        self.k8s.set_deployment_env(
            HARBOR_NAMESPACE, HARBOR_CORE, {"LOG_LEVEL": "trace"}
        )

        # Authentik components
        authentik_env_vars = {
            "AUTHENTIK_LOG_LEVEL": "debug",
            "AUTHENTIK_DEBUG": "true",
        }
        authentik_debug = {
            AUTHENTIK_SERVER: authentik_env_vars,
            AUTHENTIK_WORKER: authentik_env_vars,
        }
        self._enable_debug_for_deployments(AUTHENTIK_NAMESPACE, authentik_debug)

        # Enable PostgreSQL logging with more detail
        pg_commands = [
            "ALTER SYSTEM SET log_statement = 'all'",
            "ALTER SYSTEM SET log_duration = on",
            "ALTER SYSTEM SET log_min_duration_statement = 100",
            # Simplified log_line_prefix to avoid shell escaping issues
            "ALTER SYSTEM SET log_line_prefix = '%t [%p]: user=%u,db=%d '",
            "SELECT pg_reload_conf()",
        ]

        self.command_runner.run_psql_commands(pg_commands, log_results=True)

        # Wait for services to stabilize
        self.logger.info("Waiting 30s for services to stabilize...")
        await asyncio.sleep(30)
        self.logger.info("Debug logging enabled")

    def _enable_debug_for_deployments(
        self, namespace: str, debug_config: dict[str, dict[str, str]]
    ) -> None:
        """Enable debug logging for deployments."""
        for deployment, env_vars in debug_config.items():
            success = self.k8s.set_deployment_env(namespace, deployment, env_vars)
            if success:
                self.logger.info(f"Enabled debug logging for {deployment}")
            else:
                self.logger.error(f"Failed to enable debug for {deployment}")

    async def run_full_collection(self) -> None:
        """Run the complete data collection suite."""
        self.logger.info("Starting full data collection")

        # First enable observability (must run before other collections)
        self.logger.info("Configuring debug logging")
        await self.enable_observability()

        # Define parallel collection tasks: (name, function)
        collection_tasks = [
            ("collect_all_logs", self.log_collector.collect()),
            ("collect_k8s_resources", self.k8s_collector.collect()),
            ("collect_database_info", self.db_collector.collect()),
            ("test_api_endpoints", self.api_collector.collect()),
            ("collect_diagnostics", self.diagnostics_collector.collect()),
            ("test_oidc_e2e_flow", self.oidc_tester.test_oidc_e2e_flow()),
        ]

        # Run all collections in parallel
        results = await asyncio.gather(
            *[task for name, task in collection_tasks], return_exceptions=True
        )

        # Check results
        for (name, _), result in zip(collection_tasks, results):
            if isinstance(result, Exception):
                self.logger.error(f"{name} failed: {result}")
            else:
                self.logger.info(f"{name} completed")

        # Generate report
        self.generate_report()
        self.logger.info(f"Collection complete. Results in: {self.base_dir}")

    def generate_report(self) -> None:
        """Generate comprehensive report of data collected."""
        report = f"""
# Harbor OIDC Integration - Data Collection Report
Generated: {datetime.now()}
Directory: {self.base_dir}

## Collections Completed
- Logs: All Harbor and Authentik components
- K8s Resources: All namespaces and cluster-wide
- Databases: Schema and data dumps
- API Tests: All endpoints tested
- Diagnostics: Harbor OIDC specific checks
- E2E Tests: OIDC flow testing

## Next Steps
1. Review logs in `logs/` directory
2. Check API test results in `api_tests/`
3. Examine database configuration in `databases/`
4. Analyze K8s resources in `k8s/`
5. Check diagnostics in `diagnostics/`
6. Review E2E test results in `e2e/`

## Key Files
- `logs/harbor-core.log` - Main Harbor logs
- `api_tests/harbor-oidc-login.txt` - OIDC endpoint test
- `databases/harbor-oidc-config.txt` - OIDC configuration
- `diagnostics/internal-oidc-test.txt` - Internal OIDC test
- `e2e/oidc-test-results.txt` - E2E test results
"""

        report_file = self.base_dir / "REPORT.md"
        report_file.write_text(report)

        self.logger.info(f"Report generated: {report_file}")
