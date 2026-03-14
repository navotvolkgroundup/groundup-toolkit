"use client"

import { X } from "lucide-react"

interface CommunicationModalProps {
  isOpen: boolean
  onClose: () => void
  note: { body: string; date: string; source: string; companyName: string }
}

export default function CommunicationModal({ isOpen, onClose, note }: CommunicationModalProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="relative mx-4 max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-6 shadow-xl dark:bg-zinc-900"
        onClick={(e) => e.stopPropagation()}
      >
        <button onClick={onClose} className="absolute right-3 top-3 text-zinc-400 hover:text-zinc-600">
          <X className="h-5 w-5" />
        </button>
        <h3 className="mb-1 text-lg font-semibold">{note.companyName}</h3>
        <p className="mb-3 text-xs text-zinc-500">
          {note.source} &middot; {note.date}
        </p>
        <div className="whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-300">{note.body}</div>
      </div>
    </div>
  )
}
