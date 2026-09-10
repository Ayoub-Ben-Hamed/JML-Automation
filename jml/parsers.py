"""
CSV ingestion layer for the JML engine:
Reads UTF-8 CSV files, delegates validation to HRValidator,
and performs batch-level edge case detection such as duplicate rows, out-of-order events, and low validity ratios.
"""
import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional,Dict,List
from jml.models import EventType, HREvent, ParseResult, RowIssue, ValidationSeverity
from jml.validators import HRValidator

logger=logging.getLogger("jml.parser")

class HRCSVParser:
    """
    Orchestrates file reading, row validation, and batch analysis.
    This class is stateless — you can reuse one parser instance to process many files without cross-contamination.
    """
    EXPECTED_COLUMNS = [
        "employee_id", "email", "event_type", "department", "role",
        "first_name", "last_name", "manager_email", "start_date", "end_date",
        "old_department", "old_role",
        "employee_type", "cost_center", "location", "phone", "notes",
    ]


    def __init__(self,validator:Optional[HRValidator]=None):
        """Inject a validator or use defaults."""
        self.validator=validator or HRValidator()

    def parse(self, filepath: str) -> ParseResult:
        """Read a CSV file and return a fully-populated ParseResult.

        Handles missing files, bad encodings, and malformed headers
        without crashing the calling process.
        """
        result = ParseResult()
        path = Path(filepath)

        if not path.exists():
            logger.error(f"File not found: {filepath}")
            result.errors.append(RowIssue(0, "N/A", "file",f"File not found: {filepath}",ValidationSeverity.ERROR))
            return result

        try:
            with path.open("r",newline="",encoding="utf-8-sig") as fh:
                reader=csv.DictReader(fh)
                if reader.fieldnames is None:
                    result.errors.append(RowIssue(0,"N/A","Header","CSV is empty or had no Header row !",ValidationSeverity.ERROR))
                    return result
                reader_fieldnames=[h.strip() for h in reader.fieldnames]
                missing=set(self.EXPECTED_COLUMNS)-set(reader.fieldnames)
                if missing:
                    logger.warning(f"Missing Columns : {missing}")
                for line_no,raw in enumerate(reader,start=2):
                    result.stats["total_rows"]=result.stats.get("total_rows",0)+1
                    row={k.strip() : (v or "").strip() for k,v in raw.items()}

                    event,issues=self.validator.validate(row,line_no)

                    for issue in issues:
                        if issue.severity==ValidationSeverity.ERROR:
                            result.errors.append(issue)
                        else:
                            result.warnings.append(issue)
                    if event:
                        result.valid_events.append(event)
                        key=f"Valid_{event.event_type.value.lower()}"
                        result.stats[key]=result.stats.get(key,0)+1
                    else:
                        result.stats["invalid_rows"] = result.stats.get("invalid_rows", 0) + 1
                        logger.warning(
                            f"Line {line_no}: rejected {row.get('employee_id', 'UNKNOWN')} "
                            f"({len([i for i in issues if i.severity == ValidationSeverity.ERROR])} error(s))"
                        )
        except csv.Error as exc:
            logger.error(f"CSV syntax error: {exc}")
            result.errors.append(RowIssue(0, "N/A", "csv",f"Malformed CSV: {exc}",ValidationSeverity.ERROR))
        except Exception as exc:
            logger.error(f"Unexpected parse error: {exc}")
            result.errors.append(RowIssue(0, "N/A", "file",f"Unexpected error: {exc}",ValidationSeverity.ERROR))

        self._detect_batch_issues(result)
        return result


    def _detect_batch_issues(self, result: ParseResult) -> None:
        """
        Scan the entire result set for cross-row problems.
        Detects duplicates, temporal ordering violations, and suspiciously low validity ratios.
        """
        # Duplicate events (same emp + same type)
        seen: Dict[tuple, List[HREvent]] = defaultdict(list)
        for evt in result.valid_events:
            key = (evt.employee_id, evt.event_type.value)
            seen[key].append(evt)

        for (emp_id, evt_type), evts in seen.items():
            if len(evts) > 1:
                lines = [e.csv_line_number for e in evts]
                result.errors.append(RowIssue(
                    lines[1], emp_id, "duplicate",
                    f"Duplicate {evt_type} for {emp_id} at lines {lines}",
                    ValidationSeverity.ERROR,
                ))
                logger.error(f"Duplicate {evt_type} for {emp_id} at lines {lines}")

        # Ordering: TERMINATE before HIRE
        by_employee: Dict[str, List[HREvent]] = defaultdict(list)
        for evt in result.valid_events:
            by_employee[evt.employee_id].append(evt)

        for emp_id, evts in by_employee.items():
            sorted_evts = sorted(evts, key=lambda e: e.csv_line_number)
            types = [e.event_type for e in sorted_evts]

            if EventType.TERMINATE in types and EventType.HIRE in types:
                term_idx = next(i for i, t in enumerate(types) if t == EventType.TERMINATE)
                hire_idx = next(i for i, t in enumerate(types) if t == EventType.HIRE)
                if term_idx < hire_idx:
                    result.errors.append(RowIssue(
                        sorted_evts[term_idx].csv_line_number,
                        emp_id, "ordering",
                        f"TERMINATE (line {sorted_evts[term_idx].csv_line_number}) "
                        f"appears before HIRE (line {sorted_evts[hire_idx].csv_line_number})",
                        ValidationSeverity.ERROR,
                    ))

        # Low validity ratio
        total = result.total_rows
        if total > 0:
            ratio = result.valid_count / total
            if ratio < 0.1 and total >= 10:
                result.warnings.append(RowIssue(
                    0, "BATCH", "batch",
                    f"Only {ratio:.0%} valid ({result.valid_count}/{total}). Check CSV format.",
                    ValidationSeverity.WARNING,
                ))
                logger.warning(f"Low validity ratio: {ratio:.0%}")
