import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tedlar Lead Agent",
  description:
    "AI lead generation and outreach for DuPont Tedlar Graphics & Signage: event discovery, company enrichment, qualification, contacts and outreach drafts.",
  // The public demo lists named people at real companies. Reachable by link,
  // deliberately not indexed.
  robots: { index: false, follow: false },
};

/* Applied before first paint so the page never flashes the wrong theme, and so
   React can read the resolved theme off the DOM instead of setting state in an
   effect. Stored choice wins; otherwise follow the OS. */
const THEME_BOOTSTRAP = `
try {
  var stored = localStorage.getItem('tedlar-theme');
  var dark = stored ? stored === 'dark'
                    : window.matchMedia('(prefers-color-scheme: dark)').matches;
  if (dark) document.documentElement.classList.add('dark');
} catch (e) {}
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Script id="theme-bootstrap" strategy="beforeInteractive">
          {THEME_BOOTSTRAP}
        </Script>
        {children}
      </body>
    </html>
  );
}
