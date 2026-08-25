import { useState } from 'react';
import type { FormEvent } from 'react';
import { analyzeAcquisition, ApiError, fetchSensitivityPresets } from './api';
import { AssumptionsForm } from './components/AssumptionsForm';
import { ResultsPanel } from './components/ResultsPanel';
import { SensitivityPanel } from './components/SensitivityPanel';
import { buildAcquisitionRequest, DEFAULT_FORM_VALUES, FormValidationError } from './convert';
import type { AcquisitionFormValues, AcquisitionResults, StandardSensitivityPresets } from './types';

export default function App() {
  const [values, setValues] = useState<AcquisitionFormValues>(DEFAULT_FORM_VALUES);
  const [results, setResults] = useState<AcquisitionResults | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [sensitivity, setSensitivity] = useState<StandardSensitivityPresets | null>(null);
  const [isSensitivityLoading, setIsSensitivityLoading] = useState(false);
  const [sensitivityError, setSensitivityError] = useState<string | null>(null);

  function handleFieldChange(key: keyof AcquisitionFormValues, value: string) {
    setValues((previous) => ({ ...previous, [key]: value }));
    setResults(null);
    setError(null);
    setSensitivity(null);
    setSensitivityError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setResults(null);
    setError(null);
    setSensitivity(null);
    setSensitivityError(null);

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
        </div>
      </main>
    </div>
  );
}
