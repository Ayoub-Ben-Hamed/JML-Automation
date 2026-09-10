"""
Custom exceptions for the JML data pipeline.
Defines exception types so the engine can distinguish between
data errors (bad CSV), validation errors (bad row content),
and system errors (disk full, file locked).
"""
class JMLError(Exception):
    pass

class CSVParseError(JMLError):
    """Raised when the CSV file itself is unreadable or malformed."""
    pass

class ValidationError(Exception):
    """Raised when a single row fails business rule validation."""
    pass