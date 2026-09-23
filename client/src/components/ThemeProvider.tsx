"use client";

import { useIsDarkMode } from "@/hooks/useDarkMode";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
    const {} = useIsDarkMode();
    return <>{children}</>;
}
