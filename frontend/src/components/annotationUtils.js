export const UNSAFE_CATEGORIES = [
  'malware',
  'credential_theft',
  'phishing',
  'exploit_execution',
  'privilege_escalation',
  'evasion',
  'persistence',
  'exfiltration',
  'unauthorized_access',
  'prompt_injection',
  'data_leakage',
  'other',
  'none',
];

export function displayLabel(label) {
  return label === 'needs_human_review' ? 'Needs review' : label;
}

export function effectiveLabel(annotation) {
  const review = annotation?.human_reviews?.at(-1);
  return review?.label || annotation?.adjudication?.final_label;
}
