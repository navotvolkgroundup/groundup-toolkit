"use client"

import { cn } from "@/lib/utils"
import { ChatMessage as ChatMessageType } from "@/lib/types"
import ReactMarkdown from "react-markdown"
import { ChristinaAvatar } from "@/components/ChristinaAvatar"

export function ChatMessage({ message }: { message: ChatMessageType }) {
  const isUser = message.role === "user"

  return (
    <div className={cn("flex gap-3 px-4 py-2", isUser ? "flex-row-reverse" : "flex-row")}>
      {/* Avatar */}
      {isUser ? (
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-medium text-primary">
          NV
        </div>
      ) : (
        <ChristinaAvatar size="sm" />
      )}

      {/* Message bubble */}
      <div
        className={cn(
          "max-w-[80%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-primary text-primary-foreground rounded-tr-sm"
            : "bg-muted rounded-tl-sm"
        )}
      >
        {isUser ? (
          <p>{message.content}</p>
        ) : (
          <div className="prose prose-sm prose-invert max-w-none [&>p]:m-0 [&>ul]:my-1 [&>ol]:my-1">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>
        )}
        <p
          className={cn(
            "text-[10px] mt-1.5",
            isUser ? "text-primary-foreground/60 text-right" : "text-muted-foreground"
          )}
        >
          {message.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </p>
      </div>
    </div>
  )
}
