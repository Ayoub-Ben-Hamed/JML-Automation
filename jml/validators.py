"""
Per-row validation engine for HR CSV data.
Implements the 'fail graceful' philosophy: collect every problem in a row, then decide whether to accept, warn, or reject.
Never stop the entire batch because of one bad row
"""
import re
from typing import Optional,List,Dict,Tuple,Set
from datetime import datetime,date
from jml.models import EventType,HREvent,ValidationSeverity,RowIssue


class HRValidator:
    """
    Validates a single CSV row against business rules and type constraints.

    Operates on dictionaries (raw CSV rows) so it can report
    errors before attempting to build an HREvent.
    """
    # Regex for common formats
    _EMAIL_RE=re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9]+\.[a-zA-Z]{2,}$")
    _EMP_ID_RE=re.compile(r"^EMP-[0-9]{5,}$")
    _DATE_FMT="%Y-%m-%d"
    # Required columns vary by event type
    _REQUIRED:Dict[EventType,Set[str]]={
        EventType.HIRE: {"employee_id","email","event_type","department","role","start_date"},
        EventType.MOVE: {"employee_id","email","event_type","department","role","old_department","old_role"},
        EventType.TERMINATE: {"employee_id","email","event_type","end_date"},
        EventType.REHIRE: {"employee_id","email","event_type","department","role","start_date"},
        EventType.SUSPEND: {"employee_id","email","event_type"},
        EventType.UNSUSPEND: {"employee_id","email","event_type"}
    }

    def __init__(self,known_roles: Optional[Set[str]] = None,known_departments: Optional[Set[str]] = None,strict_mode: bool = False):
        """
        Configure the validator with reference data.
        Args:
            known_roles: Whitelist of job titles. Unknown titles : raise WARNING (or ERROR if strict_mode).
            known_departments: Whitelist of departments.
            strict_mode: If True, warnings are promoted to errors.
        """
        self.known_roles=known_roles or set()
        self.known_departments=known_departments or set()
        self.strict_mode=strict_mode
    def validate(self,row:Dict[str,str],line_number:int)->Tuple[Optional[HREvent],List[RowIssue]]:
        issues:List[RowIssue]=[]
        emp_id=row.get("employee_id","").strip()
        # 1. Parse event type
        raw_evt=row.get("event_type","").strip().upper()
        try:
            event_type=EventType(raw_evt)
        except ValueError:
            issues.append(RowIssue(line_number,emp_id or "UNKNOWN","event_type",f"Invalid {raw_evt} . Events allowed : {[e.value for e in EventType]}",ValidationSeverity.ERROR,raw_evt))
            return None,issues

        # 2. Required fields
        for field in self._REQUIRED.get(event_type, set()):
            val = row.get(field, "").strip()
            if not val or val.lower() in ("null", "none", "n/a", ""):
                issues.append(RowIssue(line_number, emp_id or "UNKNOWN", field,f"Required for {event_type.value}", ValidationSeverity.ERROR, val))
        # 3. Employee ID format
        if emp_id and not self._EMP_ID_RE.match(emp_id):
            issues.append(RowIssue(line_number, emp_id, "employee_id",f"'{emp_id}' must match EMP-XXXXX",ValidationSeverity.ERROR, emp_id))
        # 4. Email format
        email = row.get("email", "").strip()
        if email and not self._EMAIL_RE.match(email):
            issues.append(RowIssue(line_number, emp_id or "UNKNOWN", "email",f"Invalid format: '{email}'",ValidationSeverity.ERROR, email))
        # 5. Date parsing
        for dfield in ("start_date", "end_date"):
            dval = row.get(dfield, "").strip()
            if dval:
                parsed = self._parse_date(dval)
                if parsed is None:
                    issues.append(RowIssue(line_number, emp_id or "UNKNOWN", dfield,f"Invalid date '{dval}' (expected YYYY-MM-DD)",ValidationSeverity.ERROR, dval))
        # 6. Enum checks (role / department)
        role = row.get("role", "").strip()
        if role and role not in self.known_roles:
            sev = ValidationSeverity.ERROR if self.strict_mode else ValidationSeverity.WARNING
            issues.append(RowIssue(line_number, emp_id or "UNKNOWN", "role",f"Unknown role '{role}'", sev, role))
        dept = row.get("department", "").strip()
        if dept and dept not in self.known_departments:
            sev = ValidationSeverity.ERROR if self.strict_mode else ValidationSeverity.WARNING
            issues.append(RowIssue(line_number, emp_id or "UNKNOWN", "department",f"Unknown department '{dept}'", sev, dept))
        # 7. Event-specific business rules
        self._apply_business_rules(row, event_type, line_number, emp_id, issues)
        # 8. Separate fatal vs. non-fatal
        fatals = [i for i in issues if i.severity == ValidationSeverity.ERROR]
        warnings = [i for i in issues if i.severity == ValidationSeverity.WARNING]
        if fatals:
            return None, fatals + warnings
        return self._build_event(row, event_type, line_number), warnings
    def _parse_date(self, value: str) -> Optional[date]:
        """Convert a YYYY-MM-DD string to a date object."""
        try:
            return datetime.strptime(value, self._DATE_FMT).date()
        except ValueError:
            return None
    def _apply_business_rules(self,row: Dict[str, str],event_type: EventType,line_number: int,emp_id: str,issues: List[RowIssue]) -> None:
        """Run checks that depend on the event type.
        Mutates the 'issues' list in place — this avoids
        returning multiple lists and keeps the code flat.
        """
        if event_type == EventType.MOVE:
            old_d = row.get("old_department", "").strip()
            new_d = row.get("department", "").strip()
            old_r = row.get("old_role", "").strip()
            new_r = row.get("role", "").strip()
            if old_d == new_d and old_r == new_r:
                issues.append(RowIssue(line_number, emp_id or "UNKNOWN", "event_type",f"MOVE has no change (dept='{new_d}', role='{new_r}')",ValidationSeverity.WARNING, "MOVE"))
        if event_type == EventType.TERMINATE:
            end_str = row.get("end_date", "").strip()
            end_dt = self._parse_date(end_str) if end_str else None
            if end_dt and end_dt > date.today():
                issues.append(RowIssue(line_number, emp_id or "UNKNOWN", "end_date",f"Future end date {end_dt}. Will terminate on that date.",ValidationSeverity.WARNING, end_str))
        if event_type == EventType.HIRE:
            start_str = row.get("start_date", "").strip()
            start_dt = self._parse_date(start_str) if start_str else None
            if start_dt and start_dt > date.today():
                issues.append(RowIssue(line_number, emp_id or "UNKNOWN", "start_date",f"Future start date {start_dt}. Consider staging user.",ValidationSeverity.WARNING, start_str))
    def _build_event(self, row: Dict[str, str], event_type: EventType, line_number: int) -> HREvent:
        """Construct a fully-typed HREvent from a validated raw row."""
        return HREvent(
            employee_id=row.get("employee_id", "").strip(),
            email=row.get("email", "").strip(),
            event_type=event_type,
            first_name=row.get("first_name", "").strip() or None,
            last_name=row.get("last_name", "").strip() or None,
            department=row.get("department", "").strip() or None,
            role=row.get("role", "").strip() or None,
            manager_email=row.get("manager_email", "").strip() or None,
            start_date=self._parse_date(row.get("start_date", "").strip()),
            end_date=self._parse_date(row.get("end_date", "").strip()),
            old_department=row.get("old_department", "").strip() or None,
            old_role=row.get("old_role", "").strip() or None,
            employee_type=row.get("employee_type", "").strip() or None,
            cost_center=row.get("cost_center", "").strip() or None,
            location=row.get("location", "").strip() or None,
            phone=row.get("phone", "").strip() or None,
            notes=row.get("notes", "").strip() or None,
            raw_row=dict(row),
            csv_line_number=line_number,
        )
