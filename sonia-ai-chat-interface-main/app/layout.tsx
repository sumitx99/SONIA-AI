import type React from "react";
import type { Metadata } from "next";
import localFont from "next/font/local";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Analytics } from "@vercel/analytics/next";
import { Suspense } from "react";
import "./globals.css";

const editorialSerif = localFont({
  src: [
    {
      path: "../public/fonts/cormorant-medium.ttf",
      weight: "400 500",
      style: "normal",
    },
    {
      path: "../public/fonts/cormorant-semibold.ttf",
      weight: "600 700",
      style: "normal",
    },
    {
      path: "../public/fonts/cormorant-medium-italic.ttf",
      weight: "400 500",
      style: "italic",
    },
  ],
  variable: "--font-editorial",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sonia — Old soul. New mind.",
  description:
    "An intelligent reading companion. Explore your documents, follow a thought, and discover what matters.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`font-sans ${GeistSans.variable} ${GeistMono.variable} ${editorialSerif.variable}`}
      >
        <Suspense fallback={null}>{children}</Suspense>
        <Analytics />
      </body>
    </html>
  );
}
