"""Excel Export 1 -- read-only exports of saved Anchor results.

This package *consumes* Anchor's typed engine inputs and saved results and
renders them for people. It is never a source of financial truth for the
application: no engine, analysis, deals or API calculation path imports it,
and nothing it computes flows back into a stored result. See
``docs/architecture/EXCEL_EXPORT_1_QUICK_FORMULA_AUDIT.md``.
"""
