import type { HighlightColor } from "@/lib/schema";

/** Tailwind classes for highlight color picker swatches (PDF toolbar / floating sidebar). */
export const HIGHLIGHT_COLOR_SWATCHES: {
    color: HighlightColor;
    bg: string;
    label: string;
}[] = [
    { color: "yellow", bg: "bg-yellow-300", label: "Yellow" },
    { color: "green", bg: "bg-green-400", label: "Green" },
    { color: "blue", bg: "bg-blue-400", label: "Blue" },
    { color: "pink", bg: "bg-pink-400", label: "Pink" },
    { color: "purple", bg: "bg-purple-400", label: "Purple" },
];

/**
 * Soft solid fills for PDF text (opaque hex). Using translucent RGBA on saturated base
 * colors still looks loud on white, and overlapping line rects stack alpha and create dark bands.
 * [inactive, active] — inactive is ~Tailwind 100 (readable on white); active is clearly darker
 * so the focused highlight is easy to spot (not “two pastels”).
 */
export const USER_HIGHLIGHT_FILL: Record<HighlightColor, [string, string]> = {
    yellow: ["#FEF3C7", "#FDE68A"],
    green: ["#DCFCE7", "#86EFAC"],
    blue: ["#DBEAFE", "#93C5FD"],
    pink: ["#FCE7F3", "#F9A8D4"],
    purple: ["#F3E8FF", "#C4B5FD"],
};

/** @deprecated Use USER_HIGHLIGHT_FILL — kept for re-exports */
export const USER_HIGHLIGHT_RGBA = USER_HIGHLIGHT_FILL;

const ASSISTANT_HIGHLIGHT_FILL = ["#EDE9FE", "#A78BFA"] as const;

/** High-opacity, saturated colors for dark mode so highlights pop against the inverted canvas. */
const USER_HIGHLIGHT_FILL_DARK: Record<HighlightColor, [string, string]> = {
    yellow: ["#FFE066", "#FFD700"],
    green: ["#69DB7C", "#40C057"],
    blue: ["#74C0FC", "#339AF0"],
    pink: ["#F783AC", "#E64980"],
    purple: ["#CC99FF", "#B366FF"],
};

const ASSISTANT_HIGHLIGHT_FILL_DARK: [string, string] = ["#FFD966", "#FFB800"];

export function getUserHighlightBackgroundRgba(
    color: HighlightColor | undefined,
    isActive: boolean,
    darkMode?: boolean,
): string {
    if (darkMode) {
        return USER_HIGHLIGHT_FILL_DARK[color || "blue"][isActive ? 1 : 0];
    }
    return USER_HIGHLIGHT_FILL[color || "blue"][isActive ? 1 : 0];
}

export function getAssistantHighlightBackgroundRgba(
    isActive: boolean,
    darkMode?: boolean,
): string {
    if (darkMode) {
        return ASSISTANT_HIGHLIGHT_FILL_DARK[isActive ? 1 : 0];
    }
    return ASSISTANT_HIGHLIGHT_FILL[isActive ? 1 : 0];
}

/** Ephemeral text selection while dragging (matches blue inactive fill). */
export const PDF_TEXT_SELECTION_FILL = "#DBEAFE";
