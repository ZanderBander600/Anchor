from .contracts import AcquisitionInputs
from .validation import (
    InputIssue,
    InputValidationError,
    IssueCategory,
    validate_acquisition_inputs,
)


__all__ = (
    "AcquisitionInputs",
    "InputIssue",
    "InputValidationError",
    "IssueCategory",
    "read_acquisition_inputs",
    "validate_acquisition_inputs",
)


def __getattr__(name: str) -> object:
    if name == "read_acquisition_inputs":
        from .excel_reader import read_acquisition_inputs

        globals()[name] = read_acquisition_inputs
        return read_acquisition_inputs
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
