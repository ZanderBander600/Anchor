/**
 * Refinance & Capital Events V1 Stage 3 -- the Refinance & Capital Structure
 * Audit download (contract Section 25.1).
 *
 * The workbook audits the saved Analysis Variant on screen. The server decides
 * eligibility: it refuses a structure with no refinance, a refinance that did
 * not execute, and an analysis whose structured fingerprint is no longer the
 * saved state's own, each with a message that says what to do. This hook only
 * sends the fingerprint of the analysis on screen and delivers the bytes.
 * Exporting writes nothing.
 */

import { useCallback, useState } from 'react';
import { downloadRefinanceAuditWorkbook } from './api';

export type CapitalEventAuditOutcome =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'done'; filename: string }
  | { status: 'error'; message: string };

export interface CapitalEventAuditState {
  outcome: CapitalEventAuditOutcome;
  download: () => Promise<void>;
}

function save(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function useCapitalEventAudit({
  investmentId,
  strategyId,
  scenarioId,
  fingerprint,
}: {
  investmentId: string | null;
  strategyId: string;
  scenarioId: string;
  fingerprint: string | null;
}): CapitalEventAuditState {
  const [outcome, setOutcome] = useState<CapitalEventAuditOutcome>({ status: 'idle' });

  const download = useCallback(async () => {
    if (investmentId === null || fingerprint === null) {
      return;
    }
    setOutcome({ status: 'running' });
    try {
      const { blob, filename } = await downloadRefinanceAuditWorkbook(investmentId, strategyId, scenarioId, fingerprint);
      save(blob, filename);
      setOutcome({ status: 'done', filename });
    } catch (error: unknown) {
      setOutcome({
        status: 'error',
        message: error instanceof Error ? error.message : 'The refinance audit workbook could not be exported.',
      });
    }
  }, [investmentId, strategyId, scenarioId, fingerprint]);

  return { outcome, download };
}
