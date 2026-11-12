import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Creator Studio",
  description:
    "A local-first workspace for planning audio and video projects. AI features are not connected.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
