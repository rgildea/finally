import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono, Sora } from "next/font/google";
import "./globals.css";

const display = Archivo({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
});

const body = Sora({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
});

const mono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "FinAlly — AI Trading Workstation",
  description:
    "A live, AI-powered simulated trading terminal. Stream prices, trade, and let your AI copilot manage the book.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${mono.variable} h-full antialiased`}
    >
      <body className="bg-terminal text-fg-primary min-h-full font-body">
        {children}
      </body>
    </html>
  );
}
