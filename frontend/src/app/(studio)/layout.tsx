import type { ReactNode } from "react";
import { StudioShell } from "@/components/studio-shell";

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return <StudioShell>{children}</StudioShell>;
}
