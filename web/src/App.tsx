import { useState } from 'react';
import type { FormEvent } from 'react';
import { analyzeAcquisition, ApiError } from './api';
import { AssumptionsForm } from './components/AssumptionsForm';
import { ResultsPanel } from './components/ResultsPanel';
import { buildAcquisitionRequest, DEFAULT_FORM_VALUES, FormValidationError } from './convert';
import type { AcquisitionFormValues, AcquisitionResults } from './types';

export default function App() {
  const [values, setValues] = useState<AcquisitionFormValues>(DEFAULT_FORM_VALUES);
  const [results, setResults] = useState<AcquisitionResults | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleFieldChange(key: keyof AcquisitionFormValues, value: string) {
    setValues((previous) => ({ ...previous, [key]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

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
    } finally {
      setIsSubmitting(false);
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
        </div>
      </main>
    </div>
  );
}
