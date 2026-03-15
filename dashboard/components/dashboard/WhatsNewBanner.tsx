"use client"

import { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Sparkles, X, ChevronDown, ChevronUp } from "lucide-react"

const RELEASE_VERSION = "2026.03.15"
const DISMISS_KEY = `whats-new-dismissed-${RELEASE_VERSION}`

const sections = [
  {
    title: "Relationship Intelligence",
    items: [
      "Every email, meeting, and LinkedIn connection now builds a central relationship graph automatically.",
      "Signal rows show \"Connected via: Alice (3 emails)\" so you can find warm intros instantly.",
      "Deal timelines show your network connections to people at that company.",
      "Search connections and find intro paths in the new Network section.",
    ],
  },
  {
    title: "Smarter Scoring",
    items: [
      "Signal badges now show the actual composite score (0-100) instead of just High/Med/Low.",
      "Mini sparklines show score trends — green means rising, red means declining.",
      "Mark outcomes (Met, Invested, Passed, Noise) and the system learns which scoring dimensions actually predict success.",
      "After 20+ outcomes, the Scoring Insights panel shows suggested weight adjustments.",
    ],
  },
  {
    title: "Thesis-Driven Intelligence",
    items: [
      "Investment thesis areas (AI Infra, DevTools, Cybersecurity, Data, Defense) are now codified — founders matching your thesis get a score boost.",
      "Thesis fit badges appear on signal rows so you can spot aligned founders immediately.",
      "Use the \"Thesis\" filter in the signal feed to see only thesis-aligned signals.",
      "Daily thesis market scanner searches for relevant funding news and sends a WhatsApp digest at 8am.",
    ],
  },
  {
    title: "Signal-to-Deal Pipeline",
    items: [
      "One-click \"Create Deal\" on any signal — creates a HubSpot deal with company, founder contact, relationship context, and thesis fit in the note.",
      "No more manual HubSpot data entry for scout-sourced deals.",
    ],
  },
  {
    title: "Data Freshness",
    items: [
      "Every panel now shows how old its data is — green dot = fresh, amber = stale.",
      "The greeting warns you when data sources go stale so you never make decisions on outdated info.",
      "Portfolio health bar shows which companies have fresh vs aging data at a glance.",
    ],
  },
  {
    title: "Dashboard Improvements",
    items: [
      "New Portfolio section on the main dashboard with a health summary bar.",
      "Scoring Insights promoted into the Metrics row for daily visibility.",
      "Signal feed filters: All, Critical, High+, Thesis, New (unactioned).",
      "Thesis Scanner added to Quick Actions — run it anytime.",
    ],
  },
]

export function WhatsNewBanner() {
  const [dismissed, setDismissed] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    try {
      setDismissed(localStorage.getItem(DISMISS_KEY) === "true")
    } catch {
      setDismissed(false)
    }
  }, [])

  function dismiss() {
    setDismissed(true)
    try { localStorage.setItem(DISMISS_KEY, "true") } catch {}
  }

  if (dismissed) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.3 }}
        className="mb-6 rounded-xl border border-violet-500/20 bg-violet-500/5 backdrop-blur-sm overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
          >
            <Sparkles className="h-4 w-4 text-violet-400" />
            <span className="text-sm font-semibold text-violet-300">What&apos;s New</span>
            <span className="text-[10px] text-violet-400/60 bg-violet-500/10 rounded px-1.5 py-0.5 border border-violet-500/20">
              {RELEASE_VERSION}
            </span>
            {expanded
              ? <ChevronUp className="h-3.5 w-3.5 text-violet-400/60" />
              : <ChevronDown className="h-3.5 w-3.5 text-violet-400/60" />
            }
          </button>
          <button
            onClick={dismiss}
            className="p-1 rounded hover:bg-violet-500/10 transition-colors"
            title="Dismiss"
          >
            <X className="h-3.5 w-3.5 text-violet-400/60" />
          </button>
        </div>

        {/* Collapsed summary */}
        {!expanded && (
          <div className="px-5 pb-3 -mt-1">
            <p className="text-xs text-muted-foreground">
              Relationship intelligence, smarter scoring, thesis-driven market scanning, one-click signal-to-deal, and data freshness indicators.
              <button onClick={() => setExpanded(true)} className="text-violet-400 ml-1 hover:underline">
                See details
              </button>
            </p>
          </div>
        )}

        {/* Expanded release notes */}
        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="px-5 pb-5 space-y-4 max-h-[60vh] overflow-y-auto">
                {sections.map((section) => (
                  <div key={section.title}>
                    <h3 className="text-xs font-semibold text-violet-300 mb-1.5">{section.title}</h3>
                    <ul className="space-y-1">
                      {section.items.map((item, i) => (
                        <li key={i} className="text-[11px] text-muted-foreground leading-relaxed pl-3 relative before:content-[''] before:absolute before:left-0 before:top-[7px] before:h-1 before:w-1 before:rounded-full before:bg-violet-500/40">
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </AnimatePresence>
  )
}
