// Shared color utilities for recall and split badges

/** Returns Tailwind classes for recall value styling */
export function recallColorClass(value: number | null | undefined): string {
  if (value == null) return 'text-gray-400';
  if (value >= 0.7) return 'text-green-600 font-medium';
  if (value >= 0.4) return 'text-yellow-600';
  return 'text-red-600';
}

/** Returns Tailwind classes for split badge styling */
export function splitBadgeClass(split: string): string {
  switch (split) {
    case 'train':
      return 'bg-blue-100 text-blue-800';
    case 'valid':
      return 'bg-green-100 text-green-800';
    case 'test':
      return 'bg-purple-100 text-purple-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
}
