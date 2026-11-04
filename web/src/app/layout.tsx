import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flood Early Warning · Nairobi & Nyando",
  description:
    "Impact-based flood early warning prototype: where the water goes, who is exposed, where to move and which road to take.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#2563eb",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="h-full overflow-hidden">{children}</body>
    </html>
  );
}
