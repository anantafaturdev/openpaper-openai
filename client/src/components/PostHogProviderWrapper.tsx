"use client";

import dynamic from "next/dynamic";

const PostHogProvider = dynamic(
    () => import("@/lib/providers").then((m) => m.PostHogProvider),
    { ssr: false },
);

export function PostHogProviderWrapper({ children }: { children: React.ReactNode }) {
    return <PostHogProvider>{children}</PostHogProvider>;
}
