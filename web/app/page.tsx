"use client";

import dynamic from "next/dynamic";

const ChatApp = dynamic(
  () => import("@/components/ChatApp").then((mod) => mod.ChatApp),
  {
    ssr: false,
    loading: () => <div className="min-h-full bg-zinc-50" />,
  },
);

export default function Home() {
  return <ChatApp />;
}
