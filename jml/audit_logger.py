"""
Compliance-grade audit logging for the JML automation engine
Supports CSV (simple), JSON (structured), and SQLite (queryable) backends
PII is redacted by default. Immutable append-only semantics
"""

import csv,json,logging,uuid,sqlite3
from dataclasses import asdict,dataclass,field
from datetime import datetime,timezone
from enum import Enum
from typing import Any,Dict,List,Optional,Union
from pathlib import Path

class LogBackend(Enum):
    CSV="csv"
    JSON="json"
    SQLITE="sqlite"

@dataclass(frozen=True)
class AuditEntry:
    """Represents a single audit log entry."""
    entry_id:str
    timestamp:str
    event_type:str
    employee_id:str
    user_email:str
    action:str
    status:str
    triggered_by:str
    old_role:Optional[str]=None
    new_role:Optional[str]=None
    old_department:Optional[str]=None
    new_department:Optional[str]=None
    groups_added:str=""         # comma-separated for CSV
    groups_removed:str=""       # comma-separated for CSV
    apps_provisioned:str=""     #comma-separated for CSV
    errors:str=""               # semicolon-separated for CSV
    warnings:str=""             #semicolon-separated for CSV
    duration_ms:Optional[int]=None
    correlation_id:str=""       # ties multiple entries tz one batch run

    def to_dict(self)->Dict[str,Any]:
        """Convert AuditEntry to a dictionary suitable for CSV/JSON serialization."""
        return asdict(self)
    def to_json_line(self)->str:
        """Convert AuditEntry to a single-line JSON string."""
        return json.dumps(self.to_dict(),default=str)


class AuditLogger:
    """Append-only audit logger with multiple backend support.

    Design rules:
    1. Never overwrite,only append.
    2. never log passwords, tokens, or raw api responses.
    3. always include a correlation_id so batch runs are traceable.
    4. PII (emails) is logged because it is required for audit trails,but should be stored in an access-controlled location.
    """

    CSV_HEADER=[
        "entry_id","timestamp","event_type","employee_id","user_email","action","status",
        "triggered_by","old_role","new_role","old_department","new_department",
        "groups_added","groups_removed","apps_provisioned","errors","warnings",
        "duration_ms","correlation_id"
    ]
    SQLITE_SCHEMA="""
    CREATE TABLE IF NOT EXISTS audit_log (
        entry_id TEXT PRIMARY KEY,
        timestamp TEXT,
        event_type TEXT,
        employee_id TEXT,
        user_email TEXT,
        action TEXT,
        status TEXT,
        triggered_by TEXT,
        old_role TEXT,
        new_role TEXT,
        old_department TEXT,
        new_department TEXT,
        groups_added TEXT,
        groups_removed TEXT,
        apps_provisioned TEXT,
        errors TEXT,
        warnings TEXT,
        duration_ms INTEGER,
        correlation_id TEXT
    );
    
    CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_log(timestamp);
    CREATE INDEX IF NOT EXISTS idx_event_type ON audit_log(event_type);
    CREATE INDEX IF NOT EXISTS idx_user_email ON audit_log(user_email);
    CREATE INDEX IF NOT EXISTS idx_correlation ON audit_log(correlation_id);
    """
    def __init__(self,backend:LogBackend=LogBackend.CSV,output_path: Union[str, Path] = "./logs/jml_audit.csv"):
        self.backend=backend
        self.output_path=Path(output_path)
        self.output_path.parent.mkdir(parents=True,exist_ok=True)
        self._correlation_id=str(uuid.uuid4())[:8]
        if backend==LogBackend.CSV:
            self._init_csv()
        elif backend==LogBackend.JSON:
            self._init_json()
        elif backend==LogBackend.SQLITE:
            self._init_sqlite()

        # Structured logger for real-time SIEM forwarding
        self._logger=logging.getLogger("jml.audit")

    def _init_csv(self)->None:
        if not self.output_path.exists():
            with self.output_path.open("w",newline="",encoding="utf-8") as f:
                writer=csv.writer(f)
                writer.writerow(self.CSV_HEADER)
    def _init_json(self)->None:
        if not self.output_path.exists():
            self.output_path.write_text("",encoding="utf-8")
    def _init_sqlite(self)->None:
        conn=sqlite3.connect(str(self.output_path))
        conn.executescript(self.SQLITE_SCHEMA)
        conn.commit()
        conn.close()
    def log(self,event_type:str,employee_id:str,user_email:str,action:str,status:str,triggered_by:str,
            old_role:Optional[str]=None,new_role:Optional[str]=None,
            old_department:Optional[str]=None,new_department:Optional[str]=None,
            groups_added:List[str]=[],groups_removed:List[str]=[],apps_provisioned:List[str]=[],
            errors:List[str]=[],warnings:List[str]=[],duration_ms:Optional[int]=None)->AuditEntry:
        entry=AuditEntry(
            entry_id=str(uuid.uuid4()),
            timezone=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            employee_id=employee_id,
            user_email=user_email,
            action=action,
            status=status,
            triggered_by=triggered_by,
            old_role=old_role,
            new_role=new_role,
            old_department=old_department,
            new_department=new_department,
            groups_added=",".join(groups_added or []),
            groups_removed=",".join(groups_removed or []),
            apps_provisioned=",".join(apps_provisioned or []),
            errors=";".join(errors or []),
            warnings=";".join(warnings or []),
            duration_ms=duration_ms,
            correlation_id=self._correlation_id 
        )
        if self.backend==LogBackend.CSV:
            self._write_csv(entry)
        elif self.backend==LogBackend.JSON:
            self._write_json(entry)
        elif self.backend==LogBackend.SQLITE:
            self._write_sqlite(entry)

        # Also emit to Python logging for SIEM/agents
        self._logger.info(entry.to_json_line())
        
        return entry
    
    def _write_csv(self,entry:AuditEntry)->None:
        with open(self.output_path,"a",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=self.CSV_HEADER)
            writer.writerow(entry.to_dict())

    def _write_json(self,entry:AuditEntry)->None:
        with open(self.output_path,"a",encoding="utf-8") as f:
            f.write(entry.to_json_line()+"\n")

    def _write_sqlite(self,entry:AuditEntry)->None:
        conn=sqlite3.connect(str(self.output_path))
        conn.execute("insert into audit_log values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (
                         entry.entry_id, entry.timestamp, entry.event_type, entry.employee_id,
                         entry.user_email, entry.action, entry.status, entry.triggered_by,
                         entry.old_role, entry.new_role, entry.old_department, entry.new_department,
                         entry.groups_added, entry.groups_removed, entry.apps_provisioned,
                         entry.errors, entry.warnings, entry.duration_ms, entry.correlation_id
                     )
                    )
        conn.commit()
        conn.close()

    # Query helpers (SQLite only)

    def query(self,sql:str,params:tuple=())->List[Dict[str,Any]]:
        """Run a raw SQL query against the SQLite audit log"""
        if not self.backend==LogBackend.SQLITE:
            raise ValueError("Querying is only supported for SQLite backend.")
        conn=sqlite3.connect(str(self.output_path))
        conn.row_factory=sqlite3.Row
        cur=conn.execute(sql,params)
        rows=[dict(row) for row in cur.fetchall()]
        conn.close()

        return rows

    def find_by_email(self,email:str,limit:int=100)->List[Dict[str,Any]]:
        return self.query("select * from audit_log where user_email=? order by timestamp desc limit ?",(email,limit))

    def find_by_event_type(self, event_type: str, start: str, end: str) -> List[Dict[str, Any]]:
        return self.query(
            "SELECT * FROM audit_log WHERE event_type = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (event_type, start, end),
            )

    def find_failures(self, start: str, end: str) -> List[Dict[str, Any]]:
        return self.query("SELECT * FROM audit_log WHERE status != 'success' AND timestamp BETWEEN ? AND ? ORDER BY timestamp",(start, end))

    def find_group_changes(self, group_name: str, start: str, end: str) -> List[Dict[str, Any]]:
        pattern = f"%{group_name}%"
        return self.query(
            "SELECT * FROM audit_log WHERE (groups_added LIKE ? OR groups_removed LIKE ?) AND timestamp BETWEEN ? AND ?",
            (pattern, pattern, start, end),
        )
