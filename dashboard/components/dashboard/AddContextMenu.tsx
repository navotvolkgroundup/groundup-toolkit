'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import {
  Plus, Mail, MessageCircle, Mic, FileUp,
  X, Upload, Link, CheckCircle, AlertCircle
} from 'lucide-react'

interface AddContextMenuProps {
  companyName: string
  companyId?: string
  onSubmit: (type: string, data: any) => Promise<void>
}

type ContextType = 'email' | 'whatsapp' | 'granola' | 'deck' | null

export default function AddContextMenu({ companyName, companyId, onSubmit }: AddContextMenuProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [activeType, setActiveType] = useState<ContextType>(null)
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')
  const menuRef = useRef<HTMLDivElement>(null)

  // Form state
  const [emailContent, setEmailContent] = useState('')
  const [whatsappContent, setWhatsappContent] = useState('')
  const [granolaContent, setGranolaContent] = useState('')
  const [deckFile, setDeckFile] = useState<File | null>(null)
  const [deckUrl, setDeckUrl] = useState('')
  const [deckMode, setDeckMode] = useState<'upload' | 'link'>('upload')
  const [isDragging, setIsDragging] = useState(false)

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    const pdf = files.find(f =>
      f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
    )
    if (pdf) {
      setDeckFile(pdf)
    }
  }, [])

  const resetForms = () => {
    setEmailContent('')
    setWhatsappContent('')
    setGranolaContent('')
    setDeckFile(null)
    setDeckUrl('')
    setIsDragging(false)
    setError('')
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setError('')
    try {
      const data: any = { companyName, companyId }
      switch (activeType) {
        case 'email':
          data.type = 'email'
          data.content = emailContent
          break
        case 'whatsapp':
          data.type = 'whatsapp'
          data.content = whatsappContent
          break
        case 'granola':
          data.type = 'granola'
          data.content = granolaContent
          break
        case 'deck':
          data.type = 'deck'
          if (deckMode === 'link') {
            data.url = deckUrl
          } else if (deckFile) {
            const reader = new FileReader()
            const base64 = await new Promise<string>((resolve) => {
              reader.onload = () => resolve(reader.result as string)
              reader.readAsDataURL(deckFile)
            })
            data.file = base64
            data.fileName = deckFile.name
          }
          break
      }
      await onSubmit(activeType!, data)
      setSuccess(true)
      setTimeout(() => {
        setSuccess(false)
        setActiveType(null)
        resetForms()
      }, 1500)
    } catch (err: any) {
      setError(err.message || 'Failed to add context')
    } finally {
      setSubmitting(false)
    }
  }

  const isFormValid = () => {
    switch (activeType) {
      case 'email': return emailContent.trim().length > 10
      case 'whatsapp': return whatsappContent.trim().length > 5
      case 'granola': return granolaContent.trim().length > 10
      case 'deck': return deckMode === 'link' ? deckUrl.trim().startsWith('http') : !!deckFile
      default: return false
    }
  }

  const menuItems = [
    { type: 'email' as const, icon: <Mail className="w-4 h-4" />, label: 'Email', color: 'text-blue-400' },
    { type: 'whatsapp' as const, icon: <MessageCircle className="w-4 h-4" />, label: 'WhatsApp', color: 'text-green-400' },
    { type: 'granola' as const, icon: <Mic className="w-4 h-4" />, label: 'Granola Notes', color: 'text-violet-400' },
    { type: 'deck' as const, icon: <FileUp className="w-4 h-4" />, label: 'Board Deck', color: 'text-amber-400' },
  ]

  const activeItem = menuItems.find(m => m.type === activeType)

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setMenuOpen(!menuOpen)}
        className="p-1.5 rounded-lg bg-primary/10 hover:bg-primary/20 transition-colors"
        title={`Add context for ${companyName}`}
      >
        <Plus className={`w-4 h-4 text-primary transition-transform duration-200 ${menuOpen ? 'rotate-45' : ''}`} />
      </button>

      {menuOpen && !activeType && (
        <div className="absolute right-0 top-full mt-2 w-52 bg-background border border-border rounded-xl shadow-2xl z-50 py-2 overflow-hidden animate-in fade-in slide-in-from-top-2 duration-150">
          <div className="px-3 py-1.5 border-b border-border mb-1">
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
              Add context for {companyName}
            </p>
          </div>
          {menuItems.map(item => (
            <button
              key={item.type}
              onClick={() => { setActiveType(item.type); setMenuOpen(false) }}
              className="flex items-center gap-3 w-full px-3 py-2.5 text-sm text-foreground/80 hover:bg-muted/50 transition-colors"
            >
              <span className={item.color}>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </div>
      )}

      {activeType && createPortal(
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => { setActiveType(null); resetForms() }}
        >
          <div
            className="w-full max-w-xl mx-4 bg-background rounded-2xl shadow-2xl border border-border overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-muted/20">
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-lg bg-muted/50 ${activeItem?.color || ''}`}>
                  {activeItem?.icon}
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-foreground">
                    {activeItem?.label}
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    Adding to <span className="font-medium text-foreground/70">{companyName}</span>
                  </p>
                </div>
              </div>
              <button
                onClick={() => { setActiveType(null); resetForms() }}
                className="p-1.5 rounded-lg hover:bg-muted transition-colors"
              >
                <X className="w-4 h-4 text-muted-foreground" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">

              {activeType === 'email' && (
                <>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-foreground/80">
                      Email Content
                    </label>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      Paste the full email below — include the subject line, sender, date, and body.
                      Christina will extract key metrics and health signals automatically.
                    </p>
                  </div>
                  <textarea
                    value={emailContent}
                    onChange={e => setEmailContent(e.target.value)}
                    placeholder={"Subject: Q4 2025 Investor Update\nFrom: founder@company.com\nDate: March 1, 2026\n\nHi team,\n\nHere's our latest update...\n\nARR: $2.5M\nRunway: 18 months\n..."}
                    className="w-full h-56 px-4 py-3 text-sm bg-muted/20 border border-border rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 placeholder:text-muted-foreground/40 leading-relaxed"
                    autoFocus
                  />
                  <div className="flex items-start gap-2 px-3 py-2.5 bg-blue-500/5 border border-blue-500/10 rounded-lg">
                    <Mail className="w-3.5 h-3.5 text-blue-400 mt-0.5 flex-shrink-0" />
                    <p className="text-[11px] text-blue-400/80 leading-relaxed">
                      You can also forward emails directly to{' '}
                      <span className="font-mono font-semibold text-blue-400">christina@groundup.vc</span>{' '}
                      and they&apos;ll be processed automatically.
                    </p>
                  </div>
                </>
              )}

              {activeType === 'whatsapp' && (
                <>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-foreground/80">
                      WhatsApp Message
                    </label>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      Paste the WhatsApp message or conversation thread. Include timestamps and sender names if available.
                    </p>
                  </div>
                  <textarea
                    value={whatsappContent}
                    onChange={e => setWhatsappContent(e.target.value)}
                    placeholder={"[3/5/26, 2:14 PM] Founder: Hey team, quick update —\nwe just closed our first enterprise deal ($50K ACV).\nPipeline looking strong for Q2.\n\n[3/5/26, 2:15 PM] Founder: Burn is down to $80K/mo.\nRunway at 22 months now."}
                    className="w-full h-56 px-4 py-3 text-sm bg-muted/20 border border-border rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 placeholder:text-muted-foreground/40 leading-relaxed"
                    autoFocus
                  />
                </>
              )}

              {activeType === 'granola' && (
                <>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-foreground/80">
                      Meeting Notes
                    </label>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      Paste the Granola transcript or your own meeting notes.
                      Christina will extract action items, metrics, and health indicators.
                    </p>
                  </div>
                  <textarea
                    value={granolaContent}
                    onChange={e => setGranolaContent(e.target.value)}
                    placeholder={"Board Meeting — March 2026\n\nAttendees: Founder, CTO, Ground Up team\n\nKey updates:\n- ARR grew from $1.2M to $1.8M (50% QoQ)\n- Closed Series A term sheet at $15M\n- Hired VP Engineering from Stripe\n\nConcerns:\n- Customer churn ticked up to 4% monthly\n- Need to address onboarding flow\n\nAction items:\n☐ Share updated cap table by Friday\n☐ Schedule deep-dive on retention metrics"}
                    className="w-full h-56 px-4 py-3 text-sm bg-muted/20 border border-border rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 placeholder:text-muted-foreground/40 leading-relaxed"
                    autoFocus
                  />
                </>
              )}

              {activeType === 'deck' && (
                <>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-foreground/80">
                      Board Deck or Investor Update
                    </label>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      Upload a PDF or paste a DocSend link. Christina will read the full document,
                      extract key metrics, and add the context to {companyName}&apos;s portfolio record.
                    </p>
                  </div>

                  <div className="flex gap-1 p-1 bg-muted/30 rounded-lg w-fit">
                    <button
                      onClick={() => setDeckMode('upload')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                        deckMode === 'upload'
                          ? 'bg-background text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <Upload className="w-3.5 h-3.5" /> Upload PDF
                    </button>
                    <button
                      onClick={() => setDeckMode('link')}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                        deckMode === 'link'
                          ? 'bg-background text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <Link className="w-3.5 h-3.5" /> DocSend Link
                    </button>
                  </div>

                  {deckMode === 'upload' ? (
                    <div
                      onDragOver={handleDragOver}
                      onDragLeave={handleDragLeave}
                      onDrop={handleDrop}
                      className={`relative border-2 border-dashed rounded-xl p-10 text-center transition-all cursor-pointer ${
                        isDragging
                          ? 'border-primary bg-primary/5 scale-[1.01]'
                          : deckFile
                            ? 'border-emerald-500/30 bg-emerald-500/5'
                            : 'border-border hover:border-primary/30 hover:bg-muted/20'
                      }`}
                    >
                      <input
                        type="file"
                        accept=".pdf"
                        onChange={e => setDeckFile(e.target.files?.[0] || null)}
                        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                      />
                      {deckFile ? (
                        <div className="space-y-2">
                          <CheckCircle className="w-8 h-8 mx-auto text-emerald-500" />
                          <p className="text-sm font-medium text-emerald-500">{deckFile.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {(deckFile.size / 1024 / 1024).toFixed(1)} MB · Click or drop to replace
                          </p>
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <Upload className={`w-8 h-8 mx-auto ${isDragging ? 'text-primary' : 'text-muted-foreground/40'}`} />
                          <p className="text-sm text-muted-foreground">
                            {isDragging ? 'Drop PDF here' : 'Drag & drop a PDF here, or click to browse'}
                          </p>
                          <p className="text-[11px] text-muted-foreground/50">
                            Board decks, investor updates, pitch materials
                          </p>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <input
                        type="url"
                        value={deckUrl}
                        onChange={e => setDeckUrl(e.target.value)}
                        placeholder="https://docsend.com/view/..."
                        className="w-full px-4 py-3 text-sm bg-muted/20 border border-border rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 placeholder:text-muted-foreground/40"
                        autoFocus
                      />
                      <p className="text-[11px] text-muted-foreground/60 px-1">
                        Supports DocSend, Google Drive, and direct PDF links
                      </p>
                    </div>
                  )}
                </>
              )}

              {error && (
                <div className="flex items-center gap-2 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg">
                  <AlertCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
                  <p className="text-xs text-red-500">{error}</p>
                </div>
              )}

              <button
                onClick={handleSubmit}
                disabled={submitting || success || !isFormValid()}
                className={`w-full py-3 rounded-xl text-sm font-semibold transition-all ${
                  success
                    ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                    : 'bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-30 disabled:cursor-not-allowed'
                }`}
              >
                {submitting
                  ? 'Processing...'
                  : success
                    ? '✓ Added successfully'
                    : `Add to ${companyName}`
                }
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}
