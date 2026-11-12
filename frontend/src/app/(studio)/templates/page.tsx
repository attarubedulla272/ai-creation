import type { Metadata } from "next";
import { TemplatesPage } from "@/components/library-pages";

export const metadata: Metadata = { title: "Templates | AI Creator Studio" };

export default function Page() {
  return <TemplatesPage />;
}
