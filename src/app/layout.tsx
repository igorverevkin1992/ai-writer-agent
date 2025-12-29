import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Writer's Agent v2",
  description: "AI Writing Workspace",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // suppressHydrationWarning здесь ОБЯЗАТЕЛЕН для работы с расширениями
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning className="antialiased">
        {children}
      </body>
    </html>
  );
}