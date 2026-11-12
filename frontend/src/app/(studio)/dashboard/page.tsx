import type { Metadata } from "next";
import { DashboardPage } from "@/components/dashboard";

export const metadata: Metadata = { title: "Dashboard | AI Creator Studio" };

export default function Page() {
  return <DashboardPage />;
}
