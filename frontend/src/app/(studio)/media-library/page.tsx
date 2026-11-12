import type { Metadata } from "next";
import { MediaLibraryPage } from "@/components/library-pages";

export const metadata: Metadata = { title: "Media Library | AI Creator Studio" };

export default function Page() {
  return <MediaLibraryPage />;
}
