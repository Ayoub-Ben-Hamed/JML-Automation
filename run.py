"""CLI entry point for the JML data layer.

Demonstrates how to wire parser → validator → result reporter.
In production this would be triggered by a cron job, S3 event,
or message queue rather than manual execution.
"""

import logging
import sys
from pathlib import Path

from config.settings import Settings
from jml.parsers import HRCSVParser
from jml.validators import HRValidator


def setup_logging():
    """Configure structured logging to stdout and rotating files."""
    logging.basicConfig(
        level=getattr(logging, Settings.LOG_LEVEL),
        format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("logs/jml.log"),
        ],
    )


def load_reference_data():
    """Load known roles and departments from config files.

    Falls back to hardcoded defaults if files are missing
    so the engine can start even without config updates.
    """
    roles = {
        "Software Engineer", "Senior Software Engineer", "Staff Engineer",
        "Engineering Manager", "Product Manager", "Designer",
        "Sales Representative", "Account Executive", "Sales Manager",
        "HR Generalist", "HR Manager", "Finance Analyst", "CFO",
        "DevOps Engineer", "Security Engineer", "Data Scientist",
        "Intern", "Contractor",
    }
    departments = {
        "Engineering", "Product", "Design", "Sales", "Marketing",
        "HR", "Finance", "Legal", "IT", "Security", "Operations",
    }
    return roles, departments


def main():
    """Parse every CSV in the input directory and print a report."""
    setup_logging()
    logger = logging.getLogger("jml.run")

    roles, departments = load_reference_data()

    validator = HRValidator(
        known_roles=roles,
        known_departments=departments,
        strict_mode=Settings.STRICT_VALIDATION,
    )
    parser = HRCSVParser(validator=validator)

    input_dir = Settings.CSV_INPUT_DIR
    if not input_dir.exists():
        logger.error(f"Input directory does not exist: {input_dir}")
        sys.exit(1)

    csv_files = list(input_dir.glob("*.csv"))
    if not csv_files:
        logger.info("No CSV files to process.")
        return

    for csv_file in csv_files:
        logger.info(f"Processing: {csv_file.name}")
        result = parser.parse(str(csv_file))

        print(result.summary())

        for evt in result.valid_events:
            print(f"  OK  | Line {evt.csv_line_number:3d} | {evt.event_type.value:10s} | {evt.employee_id}")

        for err in result.errors:
            print(f"  ERR | Line {err.csv_line_number:3d} | {err.field:12s} | {err.message}")

        for warn in result.warnings:
            print(f"  WARN| Line {warn.csv_line_number:3d} | {warn.field:12s} | {warn.message}")


if __name__ == "__main__":
    main()