import type { Metadata } from "next";
import { ModuleWorkspace } from "@/components/module-workspaces";

export const metadata: Metadata = { title: "Content Studio | AI Creator Studio" };

export default function Page() {
  return <ModuleWorkspace slug="content-studio" />;
}
