import type { Metadata } from "next";
import { SettingsPage } from "@/components/library-pages";

export const metadata: Metadata = { title: "Settings | AI Creator Studio" };

export default function Page() {
  return <SettingsPage />;
}
