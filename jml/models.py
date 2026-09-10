from dataclasses import dataclass,field
from datetime import date
from typing import Optional,List,Dict,Any
from enum import Enum
import json

class EventType(Enum):
    """
    Allowed lifecycle events from the HR system.
    Each variant maps directly to an Okta operation:
    HIRE → create+activate, MOVE → update groups, TERMINATE → deactivate, REHIRE → reactivate
    """
    HIRE = "HIRE"
    MOVE = "MOVE"
    TERMINATE = "TERMINATE"
    REHIRE = "REHIRE"
    SUSPEND = "SUSPEND"
    UNSUSPEND = "UNSUSPEND"


class ValidationSeverity(Enum):
    """
    Classification of validation findings.
    ERROR rows are dropped from the pipeline.
    WARNING rows are processed but flagged for review
    """
    ERROR = "ERROR"
    WARNING = "WARNING"

@dataclass
class HREvent:
    """
    Represents one row from the HR CSV after parsing and typing
    """
    employee_id: str
    email: str
    event_type: EventType
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    department: Optional[str] =None
    role: Optional[str] =None
    manager_email:Optional[str] =None
    start_date: Optional[date] =None
    end_date:Optional[date] =None
    old_department: Optional[str] =None
    old_role: Optional[str] =None
    employee_type: Optional[str] =None
    cost_center: Optional[str] =None
    location: Optional[str] =None
    phone: Optional[str] =None
    notes: Optional[str] =None
    raw_row:Dict[str,str] =field(default_factory=dict,repr=False)
    csv_line_number:int =0
    def to_okta_profile(self)->Dict[str,Any]:
        """
        Translate the HR event into an Okta user profile dict.
        Uses standard Okta profile attribute names (title, manager, employeeType, costCenter, mobilePhone, employeeNumber).
        """
        profile:Dict[str,Any]={
            "login": self.email,
            "email": self.email,
        }
        if self.first_name:
            profile["firstName"] = self.first_name
        if self.last_name:
            profile["lastName"] = self.last_name
        if self.department:
            profile["department"]=self.department
        if self.role:
            profile["title"]=self.role
        if self.manager_email:
            profile["manager"]=self.manager_email
        if self.employee_type:
            profile["employeeType"]=self.employee_type
        if self.cost_center:
            profile["costCenter"]=self.cost_center
        if self.phone:
            profile["mobilePhone"]=self.phone
        if self.employee_id:
            profile["employeeNumber"]=self.employee_id
        return profile

    def to_dict(self)->Dict[str,Any]:
        """Serialize to a JSON-friendly dictionary for logging or queues"""
        return {
            "employee_id": self.employee_id,
            "email": self.email,
            "event_type": self.event_type.value,
            "department": self.department,
            "role": self.role,
            "manager_email": self.manager_email,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "old_department": self.old_department,
            "old_role": self.old_role,
            "employee_type": self.employee_type,
            "cost_center": self.cost_center,
            "location": self.location,
            "phone": self.phone,
            "notes": self.notes,
            "csv_line_number": self.csv_line_number,
        }

@dataclass
class RowIssue:
    """A single problem found in one CSV row.
    Keeps line numbers and raw values so operators can open
    the CSV, go to the exact line, and fix the source data
    """
    csv_line_number:int
    employee_id:str
    field:str
    message:str
    severity: ValidationSeverity=ValidationSeverity.ERROR
    raw_value: Optional[str]=None

@dataclass
class ParseResult:
    """
    Aggregate result of parsing an entire CSV file.
    Separates valid events, errors, and warnings so the
    caller can decide whether to proceed with Okta API calls
    """
    valid_events: List[HREvent]=field(default_factory=list)
    errors:List[RowIssue]=field(default_factory=list)
    warnings:List[RowIssue]=field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def total_rows(self) -> int:
        """Total rows seen by the parser (including invalid)"""
        return self.stats.get("total_rows", 0)
    
    @property
    def valid_count(self)->int:
        """Number of rows that passed validation""" 
        return len(self.valid_events)
    @property
    def error_count(self)->int:
        """Number of rows rejected due to errors"""
        return len(self.errors)
    @property
    def warning_count(self)->int:
        """Number of rows accepted but flagged"""
        return len(self.warnings)

    def summary(self) -> str:
        return (
            f"\n{'='*50}\n"
            f"JML Parse Result\n"
            f"{'='*50}\n"
            f"Total rows: {self.total_rows}\n"
            f"Valid: {self.valid_count}\n"
            f"Errors: {self.error_count}\n"
            f"Warnings: {self.warning_count}\n"
            f"{'='*50}"
        )
    def get_event_by_type(self,event_type:EventType)->List[HREvent]:
        """Filter valid events by lifecycle type."""
        return [e for e in self.valid_events if e.event_type==event_type]
    def get_issues_for_employee(self,employee_id:str)->List[RowIssue]:
        """Retrieve every error and warning tied to one employee"""
        return [i for i in self.errors + self.warnings if i.employee_id==employee_id]
