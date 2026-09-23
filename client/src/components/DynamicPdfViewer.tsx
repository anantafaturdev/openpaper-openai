// Dynamic wrapper for PdfHighlighterViewer that excludes it from SSR.
// pdfjs-dist (used by react-pdf-highlighter-extended) references `window` at
// module initialization time, which crashes during server-side rendering.
"use client";

import dynamic from "next/dynamic";

export const PdfHighlighterViewer = dynamic(
    () => import("@/components/PdfHighlighterViewer").then((m) => ({ default: m.PdfHighlighterViewer })),
    { ssr: false },
);
