"use client";

import dynamic from "next/dynamic";

const ChatApp = dynamic(
  () => import("@/components/ChatApp").then((mod) => mod.ChatApp),
  {
    ssr: false,
    loading: () => <div className="min-h-full" />,
  },
);

export default function Home() {
  return <ChatApp />;
}
