// Shared color utilities for recall, split badges, and issue types

/** Returns Tailwind classes for recall value styling */
export function recallColorClass(value: number | null | undefined): string {
  if (value == null) return "text-gray-400";
  if (value >= 0.7) return "text-green-600 font-medium";
  if (value >= 0.4) return "text-yellow-600";
  return "text-red-600";
}

/** Returns Tailwind classes for split badge styling */
export function splitBadgeClass(split: string): string {
  switch (split) {
    case "train":
      return "bg-blue-100 text-blue-800";
    case "valid":
      return "bg-green-100 text-green-800";
    case "test":
      return "bg-purple-100 text-purple-800";
    default:
      return "bg-gray-100 text-gray-800";
  }
}

export interface IssueColorScheme {
  bg: string;
  border: string;
  borderLeft: string;
  headerBg: string;
  text: string;
  textDark: string;
}

/** Color schemes for issue types — static class names for Tailwind scanner */
export const issueColors: Record<string, IssueColorScheme> = {
  tp: {
    bg: "bg-green-50",
    border: "border-green-200",
    borderLeft: "border-l-4 border-green-500",
    headerBg: "bg-green-100",
    text: "text-green-600",
    textDark: "text-green-700",
  },
  fp: {
    bg: "bg-red-50",
    border: "border-red-200",
    borderLeft: "border-l-4 border-red-500",
    headerBg: "bg-red-100",
    text: "text-red-600",
    textDark: "text-red-700",
  },
  critique: {
    bg: "bg-blue-50",
    border: "border-blue-200",
    borderLeft: "border-l-4 border-blue-500",
    headerBg: "bg-blue-100",
    text: "text-blue-600",
    textDark: "text-blue-700",
  },
  critiqueFp: {
    bg: "bg-orange-50",
    border: "border-orange-200",
    borderLeft: "border-l-4 border-orange-500",
    headerBg: "bg-orange-100",
    text: "text-orange-600",
    textDark: "text-orange-700",
  },
};
