import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tedlar Lead Agent",
  description:
    "AI lead generation and outreach for DuPont Tedlar Graphics & Signage: event discovery, company enrichment, qualification, contacts and outreach drafts.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
