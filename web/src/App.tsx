import { useState } from 'react';
import type { FormEvent } from 'react';
import {
  analyzeAcquisition,
  ApiError,
  fetchBreakEvenAnalysis,
  fetchSensitivityPresets,
} from './api';
import { AssumptionsForm } from './components/AssumptionsForm';
import { BreakEvenPanel } from './components/BreakEvenPanel';
import { ResultsPanel } from './components/ResultsPanel';
import { SensitivityPanel } from './components/SensitivityPanel';
import {
  buildAcquisitionRequest,
  DEFAULT_FORM_VALUES,
  DEFAULT_TARGET_EQUITY_MULTIPLE,
  DEFAULT_TARGET_HEADLINE_DSCR,
  DEFAULT_TARGET_LEVERED_IRR_PERCENT,
  FormValidationError,
  parseNumber,
  parsePercent,
} from './convert';
import type {
  AcquisitionFormValues,
  AcquisitionRequest,
  AcquisitionResults,
  ReturnHurdleMetric,
  StandardBreakEvenAnalysis,
  StandardSensitivityPresets,
} from './types';

export default function App() {
  const [values, setValues] = useState<AcquisitionFormValues>(DEFAULT_FORM_VALUES);
  const [results, setResults] = useState<AcquisitionResults | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [sensitivity, setSensitivity] = useState<StandardSensitivityPresets | null>(null);
  const [isSensitivityLoading, setIsSensitivityLoading] = useState(false);
  const [sensitivityError, setSensitivityError] = useState<string | null>(null);

  const [lastRequest, setLastRequest] = useState<AcquisitionRequest | null>(null);
  const [targetLeveredIrrPercent, setTargetLeveredIrrPercent] = useState(
    DEFAULT_TARGET_LEVERED_IRR_PERCENT,
  );
  const [targetEquityMultiple, setTargetEquityMultiple] = useState(DEFAULT_TARGET_EQUITY_MULTIPLE);
  const [targetHeadlineDscr, setTargetHeadlineDscr] = useState(DEFAULT_TARGET_HEADLINE_DSCR);
  const [returnHurdleMetric, setReturnHurdleMetric] = useState<ReturnHurdleMetric>('levered_irr');
  const [breakEven, setBreakEven] = useState<StandardBreakEvenAnalysis | null>(null);
  const [isBreakEvenLoading, setIsBreakEvenLoading] = useState(false);
  const [breakEvenError, setBreakEvenError] = useState<string | null>(null);

  function handleFieldChange(key: keyof AcquisitionFormValues, value: string) {
    setValues((previous) => ({ ...previous, [key]: value }));
    setResults(null);
    setError(null);
    setSensitivity(null);
    setSensitivityError(null);
    setLastRequest(null);
    setBreakEven(null);
    setBreakEvenError(null);
  }

  async function runBreakEven(
    request: AcquisitionRequest,
    leveredIrrPercentInput: string,
    equityMultipleInput: string,
    headlineDscrInput: string,
    metric: ReturnHurdleMetric,
  ) {
    let targetLeveredIrr: number;
    let targetEquityMultipleValue: number;
    let targetHeadlineDscrValue: number;
    try {
      targetLeveredIrr = parsePercent('Target Levered IRR', leveredIrrPercentInput);
      targetEquityMultipleValue = parseNumber('Target Equity Multiple', equityMultipleInput);
      targetHeadlineDscrValue = parseNumber('Target Year 1 DSCR', headlineDscrInput);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setBreakEven(null);
        setBreakEvenError(validationError.message);
        return;
      }
      throw validationError;
    }

    setIsBreakEvenLoading(true);
    setBreakEvenError(null);
    try {
      const analysis = await fetchBreakEvenAnalysis(
        request,
        targetLeveredIrr,
        targetEquityMultipleValue,
        targetHeadlineDscrValue,
        metric,
      );
      setBreakEven(analysis);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setBreakEvenError(apiError.message);
      } else {
        setBreakEvenError('An unexpected error occurred while calculating break-even results.');
      }
    } finally {
      setIsBreakEvenLoading(false);
    }
  }

  function handleTargetLeveredIrrChange(value: string) {
    setTargetLeveredIrrPercent(value);
    if (lastRequest) {
      void runBreakEven(lastRequest, value, targetEquityMultiple, targetHeadlineDscr, returnHurdleMetric);
    }
  }

  function handleTargetEquityMultipleChange(value: string) {
    setTargetEquityMultiple(value);
    if (lastRequest) {
      void runBreakEven(
        lastRequest,
        targetLeveredIrrPercent,
        value,
        targetHeadlineDscr,
        returnHurdleMetric,
      );
    }
  }

  function handleTargetHeadlineDscrChange(value: string) {
    setTargetHeadlineDscr(value);
    if (lastRequest) {
      void runBreakEven(
        lastRequest,
        targetLeveredIrrPercent,
        targetEquityMultiple,
        value,
        returnHurdleMetric,
      );
    }
  }

  function handleReturnHurdleMetricChange(metric: ReturnHurdleMetric) {
    setReturnHurdleMetric(metric);
    if (lastRequest) {
      void runBreakEven(
        lastRequest,
        targetLeveredIrrPercent,
        targetEquityMultiple,
        targetHeadlineDscr,
        metric,
      );
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setResults(null);
    setError(null);
    setSensitivity(null);
    setSensitivityError(null);
    setLastRequest(null);
    setBreakEven(null);
    setBreakEvenError(null);

    let request;
    try {
      request = buildAcquisitionRequest(values);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setError(validationError.message);
        return;
      }
      throw validationError;
    }

    setIsSubmitting(true);
    try {
      const nextResults = await analyzeAcquisition(request);
      setResults(nextResults);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setError(apiError.message);
      } else {
        setError('An unexpected error occurred while analyzing the deal.');
      }
      setIsSubmitting(false);
      return;
    }
    setIsSubmitting(false);
    setLastRequest(request);

    setIsSensitivityLoading(true);
    try {
      const presets = await fetchSensitivityPresets(request);
      setSensitivity(presets);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setSensitivityError(apiError.message);
      } else {
        setSensitivityError('An unexpected error occurred while calculating sensitivity.');
      }
    } finally {
      setIsSensitivityLoading(false);
    }

    await runBreakEven(
      request,
      targetLeveredIrrPercent,
      targetEquityMultiple,
      targetHeadlineDscr,
      returnHurdleMetric,
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Mini-Anchor</h1>
        <p>Commercial Real Estate Acquisition Analysis</p>
      </header>

      <main className="app-main">
        <AssumptionsForm
          values={values}
          onFieldChange={handleFieldChange}
          onSubmit={handleSubmit}
          isSubmitting={isSubmitting}
        />

        <div className="results-column">
          {error && <div className="error-banner">{error}</div>}

          {!results && !error && (
            <div className="empty-state">
              Enter assumptions and click <strong>Analyze Deal</strong> to see results.
            </div>
          )}

          {results && <ResultsPanel results={results} />}

          {results && (
            <SensitivityPanel
              presets={sensitivity}
              isLoading={isSensitivityLoading}
              error={sensitivityError}
            />
          )}

          {results && (
            <BreakEvenPanel
              analysis={breakEven}
              isLoading={isBreakEvenLoading}
              error={breakEvenError}
              targetLeveredIrrPercent={targetLeveredIrrPercent}
              targetEquityMultiple={targetEquityMultiple}
              targetHeadlineDscr={targetHeadlineDscr}
              returnHurdleMetric={returnHurdleMetric}
              onTargetLeveredIrrChange={handleTargetLeveredIrrChange}
              onTargetEquityMultipleChange={handleTargetEquityMultipleChange}
              onTargetHeadlineDscrChange={handleTargetHeadlineDscrChange}
              onReturnHurdleMetricChange={handleReturnHurdleMetricChange}
            />
          )}
        </div>
      </main>
    </div>
  );
}
