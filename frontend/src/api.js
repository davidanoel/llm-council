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

  annotate(payload) {
    return request('/api/annotate', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  annotateBatch(prompts) {
    return request('/api/annotate/batch-with-progress', {
      method: 'POST',
      body: JSON.stringify({ prompts }),
    });
  },

  annotateCsv(csvText) {
    return request('/api/annotate/csv', {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv' },
      body: csvText,
    });
  },

  listAnnotations() {
    return request('/api/annotations');
  },

  getAnnotation(promptId) {
    return request(`/api/annotations/${encodeURIComponent(promptId)}`);
  },

  reviewQueue() {
    return request('/api/review-queue');
  },

  humanReview(payload) {
    return request('/api/human-review', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  exportLabels(includePromptText = false) {
    return request(`/api/export-labels?include_prompt_text=${includePromptText}`);
  },

  evaluate(labels) {
    return request('/api/evaluate', {
      method: 'POST',
      body: JSON.stringify({ labels }),
    });
  },
};
