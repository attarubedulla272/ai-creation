import type { Metadata } from "next";
import { ProjectsPage } from "@/components/dashboard";

export const metadata: Metadata = { title: "Projects | AI Creator Studio" };

export default function Page() {
  return <ProjectsPage />;
}
