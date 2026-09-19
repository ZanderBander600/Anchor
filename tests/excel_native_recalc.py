"""Excel Export 1 test support: recalculate disposable workbooks in a real
spreadsheet engine.

Desktop Excel is driven through COM from one PowerShell process: each
workbook is opened read-only, fully rebuilt (``CalculateFullRebuild``) and
saved as a new ``.xlsx`` beside it, so the saved cached values are Excel's own
results. Nothing here is a production dependency -- it exists only so tests
can read what Excel actually calculates instead of trusting cached values.

Opt-in: set ``ANCHOR_EXCEL_NATIVE_RECALC=1``. Launching a desktop application
is too heavy and too machine-specific for the default suite, and a machine
without Excel must skip rather than pretend.

Process hygiene: the script records the process id of the Excel instance it
created (from its window handle) and, after ``Quit``, terminates that one
process if it is still alive. It never touches any other Excel process.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ENABLE_VARIABLE = "ANCHOR_EXCEL_NATIVE_RECALC"

_SCRIPT = r"""
param([string]$Manifest)
$ErrorActionPreference = 'Stop'
Add-Type -Namespace AnchorQa -Name Win32 -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern uint GetWindowThreadProcessId(System.IntPtr hWnd, out uint processId);
'@
$excel = New-Object -ComObject Excel.Application
$excelPid = 0
[void][AnchorQa.Win32]::GetWindowThreadProcessId([System.IntPtr]$excel.Hwnd, [ref]$excelPid)
try {
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.AutomationSecurity = 3
    foreach ($line in Get-Content -LiteralPath $Manifest) {
        if (-not $line) { continue }
        $parts = $line.Split('|')
        $workbook = $excel.Workbooks.Open($parts[0], 0, $true)
        $excel.CalculateFullRebuild()
        $workbook.SaveAs($parts[1], 51)
        $workbook.Close($false)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($workbook)
    }
} finally {
    $excel.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    Start-Sleep -Milliseconds 500
    $leftover = Get-Process -Id $excelPid -ErrorAction SilentlyContinue
    if ($leftover) { Stop-Process -Id $excelPid -Force }
}
"""


def native_recalc_enabled() -> bool:
    return sys.platform == "win32" and os.environ.get(ENABLE_VARIABLE) == "1"


def recalculate_with_excel(pairs: list[tuple[Path, Path]], work_dir: Path) -> None:
    """Recalculate each ``(source, destination)`` pair in one Excel session."""

    script = work_dir / "anchor_excel_recalc.ps1"
    manifest = work_dir / "anchor_excel_recalc_manifest.txt"
    script.write_text(_SCRIPT, encoding="utf-8")
    manifest.write_text(
        "\n".join(f"{source.resolve()}|{destination.resolve()}" for source, destination in pairs),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Manifest",
            str(manifest),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Excel recalculation failed ({completed.returncode}): {completed.stderr.strip()}"
        )
    missing = [str(destination) for _, destination in pairs if not destination.exists()]
    if missing:
        raise RuntimeError(f"Excel did not write: {missing}")
