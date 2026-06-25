const API_BASE = 'http://localhost:8001';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return response.json();
}

export const api = {
  health() {
    return request('/api/health');
  },

  annotateCsv(csvText, { runName, sourceFilename } = {}) {
    const params = new URLSearchParams();
    if (runName) params.set('run_name', runName);
    if (sourceFilename) params.set('source_filename', sourceFilename);
    const suffix = params.toString() ? `?${params}` : '';
    return request(`/api/runs/csv${suffix}`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv' },
      body: csvText,
    });
  },

  validateCsv(csvText) {
    return request('/api/runs/csv/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv' },
      body: csvText,
    });
  },

  listRuns() {
    return request('/api/runs');
  },

  getRun(runId) {
    return request(`/api/runs/${encodeURIComponent(runId)}`);
  },

  runItems(runId) {
    return request(`/api/runs/${encodeURIComponent(runId)}/items`);
  },

  deleteAnnotation(runId, promptId) {
    return request(`/api/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(promptId)}`, {
      method: 'DELETE',
    });
  },

  deleteRun(runId) {
    return request(`/api/runs/${encodeURIComponent(runId)}`, {
      method: 'DELETE',
    });
  },

  runAgreement(runId) {
    return request(`/api/runs/${encodeURIComponent(runId)}/agreement`);
  },

  analyzeExportCsv(csvText) {
    return request('/api/exports/analyze-csv', {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv' },
      body: csvText,
    });
  },

  runReviewQueue(runId) {
    return request(`/api/runs/${encodeURIComponent(runId)}/review-queue`);
  },

  humanReview(payload) {
    return request('/api/human-review', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  exportRunLabels(runId, includePromptText = false) {
    return request(`/api/runs/${encodeURIComponent(runId)}/export-labels?include_prompt_text=${includePromptText}`);
  },

  async exportLabelsCsv(runId, includePromptText = false) {
    const path = `/api/runs/${encodeURIComponent(runId)}/export-labels.csv?include_prompt_text=${includePromptText}`;
    const response = await fetch(`${API_BASE}${path}`);
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || `Request failed: ${response.status}`);
    }
    return response.blob();
  },
};
