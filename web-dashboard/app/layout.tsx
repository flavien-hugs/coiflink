import type { Metadata } from "next";
import { Fraunces, Outfit } from "next/font/google";
import "./globals.css";
import { SITE_DESCRIPTION, SITE_NAME } from "@/src/domain/site";

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-outfit",
  weight: ["400", "500", "600", "700"],
});

// Police serif éditoriale des titres (H1/H2, cf. identité visuelle) — Outfit
// reste la police de toute l'interface fonctionnelle (boutons, tableaux,
// formulaires) ; Fraunces n'habille que les titres de section.
const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: SITE_NAME,
  description: SITE_DESCRIPTION,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr" className={`${outfit.variable} ${fraunces.variable}`}>
      <body className="flex min-h-screen flex-col bg-background font-sans text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
