import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ConsoleLayout } from "@/components/layout/console-layout";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "agentsOnAir Console",
  description:
    "Autonomous software engineering and code review platform that develops, tests, and verifies code inside isolated sandboxes.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <ConsoleLayout>{children}</ConsoleLayout>
        <Toaster />
      </body>
    </html>
  );
}
