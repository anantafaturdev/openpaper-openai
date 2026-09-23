import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "../globals.css";
import { AppSidebar } from "@/components/sidebar/AppSidebar";
import { AppHeader } from "@/components/AppHeader";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AuthProvider } from "@/lib/auth";

import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "@/components/ThemeProvider";
import { PostHogProviderWrapper } from "@/components/PostHogProviderWrapper";
import { SidebarController } from "@/components/utils/SidebarAutoCollapse";

const geistSans = Geist({
    variable: "--font-geist-sans",
    subsets: ["latin"],
});

const geistMono = Geist_Mono({
    variable: "--font-geist-mono",
    subsets: ["latin"],
});

export const metadata: Metadata = {
    title: "Open Paper",
    description:
        "The fastest way to annotate and deeply understand research papers.",
    icons: {
        icon: "/icon.svg",
    },
    openGraph: {
        title: "Open Paper",
        description:
            "The fastest way to annotate and deeply understand research papers.",
        images: [
            {
                url: "https://assets.khoj.dev/openpaper/hero_open_paper2.png",
                width: 1280,
                height: 640,
                alt: "Open Paper",
            },
        ],
        type: "website",
    },
    twitter: {
        card: "summary_large_image",
        title: "Open Paper",
        description:
            "The fastest way to annotate and deeply understand your research papers.",
        images: ["https://assets.khoj.dev/openpaper/hero_open_paper2.png"],
    },
};

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en" suppressHydrationWarning>
            <head>
                <script
                    id="theme-script"
                    dangerouslySetInnerHTML={{
                        __html: `
      try {
        if (localStorage.getItem('darkMode') === 'dark' ||
            (!localStorage.getItem('darkMode') && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }
      } catch (e) {}
    `,
                    }}
                />
                <script
                    defer
                    data-domain="openpaper.ai"
                    src="https://plausible.io/js/script.js"
                ></script>
            </head>
            <body
                className={`${geistSans.variable} ${geistMono.variable} antialiased`}
            >
                <ThemeProvider>
                    <AuthProvider>
                        <PostHogProviderWrapper>
                            <SidebarProvider>
                                <AppSidebar />
                                <SidebarInset>
                                    <AppHeader />
                                    <SidebarController>
                                        {children}
                                    </SidebarController>
                                </SidebarInset>
                            </SidebarProvider>
                        </PostHogProviderWrapper>
                    </AuthProvider>
                </ThemeProvider>
                <Toaster position="top-right" richColors duration={3000} />
            </body>
        </html>
    );
}
