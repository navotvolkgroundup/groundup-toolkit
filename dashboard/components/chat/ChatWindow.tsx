"use client"

import { useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Trash2 } from "lucide-react"
import { ChristinaAvatar } from "@/components/ChristinaAvatar"
import { Button } from "@/components/ui/button"
import { useChatStore } from "@/lib/store/chatStore"
import { ChatMessage } from "./ChatMessage"
import { ChatInput } from "./ChatInput"
import { TypingIndicator } from "./TypingIndicator"
import { OnlineDot } from "@/components/layout/StatusBadge"

export function ChatWindow() {
  const {
    isOpen,
    closeChat,
    messages,
    isStreaming,
    serviceContextName,
    clearChat,
  } = useChatStore()
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isStreaming])

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop on mobile */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={closeChat}
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm sm:hidden"
          />

          {/* Panel */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="fixed right-0 top-0 z-50 flex h-screen w-full flex-col border-l border-border bg-card/95 backdrop-blur-xl sm:w-[400px]"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <div className="flex items-center gap-3">
                <ChristinaAvatar size="sm" />
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">Christina</span>
                    <OnlineDot online />
                  </div>
                  <span className="text-[10px] text-muted-foreground">AI Assistant</span>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={clearChat}
                  className="h-8 w-8 text-muted-foreground hover:text-foreground"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={closeChat}
                  className="h-8 w-8 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* Context banner */}
            {serviceContextName && (
              <div className="flex items-center gap-2 border-b border-border bg-primary/5 px-4 py-2">
                <span className="text-xs text-primary">
                  Chatting about: <span className="font-medium">{serviceContextName}</span>
                </span>
              </div>
            )}

            {/* Messages */}
            <div ref={scrollRef} className="flex-1 overflow-y-auto py-4">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-center px-8">
                  <ChristinaAvatar size="xl" className="mb-4" />
                  <p className="text-sm font-medium mb-1">Hey, I&apos;m Christina</p>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    Your AI assistant at GroundUp. Ask me about deals, meetings, portfolio companies, or any service.
                  </p>
                </div>
              )}
              {messages.map((msg) => (
                <ChatMessage key={msg.id} message={msg} />
              ))}
              {isStreaming && messages[messages.length - 1]?.content === "" && (
                <div className="px-4">
                  <TypingIndicator />
                </div>
              )}
            </div>

            {/* Input */}
            <ChatInput />
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
