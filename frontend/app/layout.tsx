import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Kesh Kala | Salon, Grooming & Care",
  description: "Talk to Tara, your personal salon receptionist. Explore services and plan your next appointment with Kesh Kala.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} min-h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
