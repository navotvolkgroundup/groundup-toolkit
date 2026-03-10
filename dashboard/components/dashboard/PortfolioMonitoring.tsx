"use client"

import { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Building2, X, Activity, TrendingUp, TrendingDown, AlertTriangle, Loader2, ExternalLink, ChevronRight, ChevronDown, FileText, Upload } from "lucide-react"
import { cn } from "@/lib/utils"
import CommunicationModal from "./CommunicationModal"
import AddContextMenu from "./AddContextMenu"
import { Mail, MessageCircle, Mic } from "lucide-react"
import { COMPANY_DESCRIPTIONS } from "@/lib/companyDescriptions"

interface Company {
  name: string
  domain: string
  fund: "I" | "II"
  companyId: string | null
  health: "GREEN" | "YELLOW" | "RED" | null
  lastUpdate: string | null
  summary: string | null
  revenueMetric: string | null
  metrics: { arr: string | null; mrr: string | null; runway: string | null; headcount: string | null; momGrowth: string | null }
  redFlags: string[]
  goodNews: string[]
  updateCount: number
}

interface Summary {
  total: number; green: number; yellow: number; red: number; noData: number
}

interface CompanyDetail {
  notes: Array<{ id: string; body: string; date: string; dateMs: number; source: string }>
  touchpoints30d: number
  analysis: string
}

interface NewsItem {
  title: string; link: string; pubDate: string; source: string
}

interface InvestmentEntry {
  asset: string; investmentDate: string; shares: number | null; cost: number; value: number
  lastValuationDate: string; gainLoss: number; costPerShare: number | null; fmvPerShare: number | null
  percentOfPartnersCapital: number | null; blendedMultiple: number | null
  pctCapital?: string
}

type CommunicationSource = "email" | "whatsapp" | "granola" | "update"

function detectSource(noteBody: string): CommunicationSource {
  if (noteBody.includes("\u2014 Email") || noteBody.includes("Source: Email Update")) return "email"
  if (noteBody.includes("\u2014 WhatsApp") || noteBody.includes("Source: WhatsApp")) return "whatsapp"
  if (noteBody.includes("\u2014 Meeting") || noteBody.includes("Source: Meeting Notes")) return "granola"
  return "update"
}

const ARCHIVED_COMPANIES = [
  '402', 'BigBrain', 'BrightHire', 'DemoLeap',
  'Driift Holdings', 'Good Mvmt', 'Hello Wonder', 'OptimalQ',
]

const healthColor: Record<string, string> = { GREEN: "bg-emerald-500", YELLOW: "bg-amber-500", RED: "bg-red-500" }
const healthBorder: Record<string, string> = { GREEN: "border-emerald-500/30", YELLOW: "border-amber-500/30", RED: "border-red-500/30" }

function formatCurrency(val: number | null): string {
  if (val === null || val === undefined) return "\u2014"
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(val)
}

export function PortfolioMonitoring() {
  const [companies, setCompanies] = useState<Company[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Company | null>(null)
  const [detail, setDetail] = useState<CompanyDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [fundFilter, setFundFilter] = useState<"all" | "I" | "II" | "archived">("all")
  const [healthFilter, setHealthFilter] = useState<string>("all")
  const [selectedNote, setSelectedNote] = useState<{ body: string; date: string; source: CommunicationSource; companyName: string } | null>(null)
  const [investments, setInvestments] = useState<InvestmentEntry[]>([])
  const [news, setNews] = useState<NewsItem[]>([])
  const [generatingTearSheet, setGeneratingTearSheet] = useState(false)
  const [soiExpanded, setSoiExpanded] = useState(false)

  useEffect(() => {
    fetch("/api/portfolio")
      .then(r => r.json())
      .then(d => { setCompanies(d.companies || []); setSummary(d.summary) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!selected) { setDetail(null); setInvestments([]); setNews([]); setSoiExpanded(false); return }
    setDetailLoading(true)
    Promise.all([
      fetch(`/api/portfolio/${encodeURIComponent(selected.name)}`).then(r => r.json()).catch(() => ({ notes: [], touchpoints30d: 0, analysis: "" })),
      fetch(`/api/portfolio/investment-data?company=${encodeURIComponent(selected.name)}`).then(r => r.json()).catch(() => ({ investments: [] })),
    ]).then(([d, inv]) => {
      setDetail(d)
      setInvestments(inv.investments || [])
    }).finally(() => setDetailLoading(false))

    // Fetch news
    const domain = selected.domain || ''
    fetch(`/api/portfolio/news?company=${encodeURIComponent(selected.name)}&domain=${encodeURIComponent(domain)}`)
      .then(r => r.json())
      .then(d => setNews(d.news || []))
      .catch(() => setNews([]))
  }, [selected])

  const archivedCount = companies.filter(c => ARCHIVED_COMPANIES.includes(c.name)).length
  const activeCompanies = companies.filter(c => !ARCHIVED_COMPANIES.includes(c.name))

  const filtered = companies.filter(c => {
    const isArchived = ARCHIVED_COMPANIES.includes(c.name)
    if (fundFilter === 'archived') return isArchived
    if (isArchived) return false
    if (fundFilter !== "all" && c.fund !== fundFilter) return false
    if (healthFilter === "noData" && c.health !== null) return false
    if (healthFilter !== "all" && healthFilter !== "noData" && c.health !== healthFilter) return false
    return true
  })

  const generateTearSheet = async () => {
    if (!selected) return
    setGeneratingTearSheet(true)
    try {
      const res = await fetch('/api/portfolio/tear-sheet', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          companyName: selected.name,
          description: COMPANY_DESCRIPTIONS[selected.name] || '',
          fund: selected.fund,
          health: selected.health,
          metrics: selected.metrics,
          investments,
        }),
      })
      if (!res.ok) throw new Error('Failed to generate')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${selected.name.replace(/[^a-zA-Z0-9]/g, '_')}_Tear_Sheet.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Tear sheet error:', err)
    } finally {
      setGeneratingTearSheet(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold">Portfolio Monitoring</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {activeCompanies.length} active companies across Fund I & II
          </p>
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-5 gap-3 mb-6">
          <button onClick={() => setHealthFilter("all")} className={cn("rounded-xl border p-4 text-center transition-colors", healthFilter === "all" ? "border-primary bg-primary/5" : "border-border bg-card/50 hover:bg-muted/30")}>
            <div className="text-2xl font-bold">{activeCompanies.length}</div>
            <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">Active</div>
          </button>
          <button onClick={() => setHealthFilter("GREEN")} className={cn("rounded-xl border p-4 text-center transition-colors", healthFilter === "GREEN" ? "border-emerald-500 bg-emerald-500/5" : "border-border bg-card/50 hover:bg-muted/30")}>
            <div className="text-2xl font-bold text-emerald-500">{summary.green}</div>
            <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">Green</div>
          </button>
          <button onClick={() => setHealthFilter("YELLOW")} className={cn("rounded-xl border p-4 text-center transition-colors", healthFilter === "YELLOW" ? "border-amber-500 bg-amber-500/5" : "border-border bg-card/50 hover:bg-muted/30")}>
            <div className="text-2xl font-bold text-amber-500">{summary.yellow}</div>
            <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">Yellow</div>
          </button>
          <button onClick={() => setHealthFilter("RED")} className={cn("rounded-xl border p-4 text-center transition-colors", healthFilter === "RED" ? "border-red-500 bg-red-500/5" : "border-border bg-card/50 hover:bg-muted/30")}>
            <div className="text-2xl font-bold text-red-500">{summary.red}</div>
            <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">Red</div>
          </button>
          <button onClick={() => setHealthFilter("noData")} className={cn("rounded-xl border p-4 text-center transition-colors", healthFilter === "noData" ? "border-primary bg-primary/5" : "border-border bg-card/50 hover:bg-muted/30")}>
            <div className="text-2xl font-bold text-muted-foreground">{summary.noData}</div>
            <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">No Data</div>
          </button>
        </div>
      )}

      {/* Fund filter + Archived tab */}
      <div className="flex gap-2 mb-4">
        {(["all", "I", "II"] as const).map(f => (
          <button key={f} onClick={() => setFundFilter(f)}
            className={cn("px-3 py-1.5 rounded-lg text-xs font-medium transition-colors", fundFilter === f ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground")}
          >
            {f === "all" ? "All Funds" : `Fund ${f}`}
          </button>
        ))}
        <button
          onClick={() => setFundFilter('archived')}
          className={cn("px-3 py-1.5 rounded-lg text-xs font-medium transition-colors", fundFilter === 'archived' ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}
        >
          Archived
          <span className="ml-1 text-muted-foreground/60">{archivedCount}</span>
        </button>
      </div>

      {/* Company grid */}
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filtered.map(co => (
          <motion.div
            key={co.name}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn(
              "rounded-xl border bg-card/50 backdrop-blur-sm p-4 cursor-pointer hover:bg-muted/30 transition-all group",
              co.health ? healthBorder[co.health] : "border-border"
            )}
            onClick={() => setSelected(co)}
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                {co.health && <div className={cn("w-2 h-2 rounded-full", healthColor[co.health])} />}
                <span className="text-sm font-medium truncate">{co.name}</span>
              </div>
              <span className="text-[9px] text-muted-foreground px-1.5 py-0.5 rounded bg-muted/50">
                Fund {co.fund}
              </span>
            </div>
            {co.revenueMetric && (
              <div className="text-xs text-foreground/80 mb-1.5 font-mono">{co.revenueMetric}</div>
            )}
            {co.summary ? (
              <p className="text-[10px] text-muted-foreground line-clamp-2 leading-relaxed">{co.summary}</p>
            ) : (
              <p className="text-[10px] text-muted-foreground/50 italic">No updates yet</p>
            )}
            {co.redFlags.length > 0 && (
              <div className="flex items-center gap-1 mt-2 text-[9px] text-red-400">
                <AlertTriangle className="w-3 h-3" />
                {co.redFlags[0].slice(0, 50)}
              </div>
            )}
            <div className="flex items-center justify-between mt-3 pt-2 border-t border-border/50">
              <span className="text-[9px] text-muted-foreground">{co.lastUpdate || "Never"}</span>
              <div className="flex items-center gap-1 text-[9px] text-muted-foreground">
                {co.updateCount > 0 && <span>{co.updateCount} updates</span>}
                <ChevronRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Slide-over panel */}
      <AnimatePresence>
        {selected && (
          <>
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
              onClick={() => setSelected(null)}
            />
            <motion.div
              initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
              transition={{ type: "spring", damping: 30, stiffness: 300 }}
              className="fixed right-0 top-0 z-50 h-screen w-full max-w-xl bg-background border-l border-border shadow-2xl overflow-y-auto"
            >
              {/* Header */}
              <div className="sticky top-0 z-10 bg-background/95 backdrop-blur-sm border-b border-border px-6 py-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {selected.health && <div className={cn("w-3 h-3 rounded-full", healthColor[selected.health])} />}
                    <div>
                      <h2 className="text-lg font-semibold">{selected.name}</h2>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span>Fund {selected.fund}</span>
                        {selected.domain && (
                          <>
                            <span>&middot;</span>
                            <a href={`https://${selected.domain}`} target="_blank" rel="noopener noreferrer"
                               className="hover:text-primary transition-colors inline-flex items-center gap-1">
                              {selected.domain}
                              <ExternalLink className="w-2.5 h-2.5" />
                            </a>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={generateTearSheet}
                      disabled={generatingTearSheet}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-border text-muted-foreground hover:text-foreground hover:border-primary/30 transition-colors disabled:opacity-50"
                    >
                      <FileText className="w-3.5 h-3.5" />
                      {generatingTearSheet ? 'Generating...' : 'Tear Sheet'}
                    </button>
                    <AddContextMenu
                      companyName={selected.name}
                      companyId={selected.companyId || undefined}
                      onSubmit={async (_type, data) => {
                        await fetch("/api/portfolio/add-context", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify(data),
                        })
                        const d = await fetch(`/api/portfolio/${encodeURIComponent(selected.name)}`).then(r => r.json())
                        setDetail(d)
                      }}
                    />
                    <button onClick={() => setSelected(null)} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
                      <X className="w-4 h-4 text-muted-foreground" />
                    </button>
                  </div>
                </div>
              </div>

              <div className="px-6 py-5 space-y-6">
                {detailLoading ? (
                  <div className="flex items-center justify-center h-40">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : (
                  <>
                    {/* Description */}
                    {COMPANY_DESCRIPTIONS[selected.name] && (
                      <div>
                        <p className="text-sm text-foreground/70 leading-relaxed">
                          {COMPANY_DESCRIPTIONS[selected.name]}
                        </p>
                      </div>
                    )}

                    {/* Recent News */}
                    {news.length > 0 && (
                      <div>
                        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Recent News</h3>
                        <div className="space-y-2">
                          {news.map((item, i) => (
                            <a key={i} href={item.link} target="_blank" rel="noopener noreferrer"
                              className="block px-3 py-2.5 rounded-lg border border-border/50 hover:bg-muted/20 hover:border-primary/20 transition-colors group">
                              <p className="text-sm text-foreground group-hover:text-primary transition-colors line-clamp-2">{item.title}</p>
                              <div className="flex items-center gap-2 mt-1 text-[10px] text-muted-foreground">
                                {item.source && <span>{item.source}</span>}
                                {item.source && item.pubDate && <span>&middot;</span>}
                                {item.pubDate && <span>{new Date(item.pubDate).toLocaleDateString()}</span>}
                              </div>
                            </a>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Metrics */}
                    {selected.health && (
                      <div className="grid grid-cols-3 gap-2">
                        {selected.metrics.arr && (
                          <div className="bg-muted/30 rounded-lg p-3">
                            <div className="text-[10px] text-muted-foreground uppercase">ARR</div>
                            <div className="text-sm font-semibold">{selected.metrics.arr}</div>
                          </div>
                        )}
                        {selected.metrics.mrr && (
                          <div className="bg-muted/30 rounded-lg p-3">
                            <div className="text-[10px] text-muted-foreground uppercase">MRR</div>
                            <div className="text-sm font-semibold">{selected.metrics.mrr}</div>
                          </div>
                        )}
                        {selected.metrics.runway && (
                          <div className="bg-muted/30 rounded-lg p-3">
                            <div className="text-[10px] text-muted-foreground uppercase">Runway</div>
                            <div className="text-sm font-semibold">{selected.metrics.runway}</div>
                          </div>
                        )}
                        {selected.metrics.headcount && (
                          <div className="bg-muted/30 rounded-lg p-3">
                            <div className="text-[10px] text-muted-foreground uppercase">Headcount</div>
                            <div className="text-sm font-semibold">{selected.metrics.headcount}</div>
                          </div>
                        )}
                        {selected.metrics.momGrowth && (
                          <div className="bg-muted/30 rounded-lg p-3">
                            <div className="text-[10px] text-muted-foreground uppercase">MoM Growth</div>
                            <div className="text-sm font-semibold">{selected.metrics.momGrowth}</div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* AI Analysis */}
                    {detail?.analysis && (
                      <div>
                        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">AI Analysis</h3>
                        <div className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed bg-muted/20 rounded-lg p-4 border border-border/50">
                          {detail.analysis}
                        </div>
                      </div>
                    )}

                    {/* Investment Data (SOI Table) */}
                    {(investments.length > 0) && (
                      <div>
                        <button onClick={() => setSoiExpanded(!soiExpanded)} className="flex items-center gap-2 w-full text-left group">
                          {soiExpanded ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />}
                          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Investment Data</h3>
                          {!soiExpanded && investments.length > 0 && (
                            <span className="text-xs text-muted-foreground ml-auto">
                              {formatCurrency(investments.reduce((s, i) => s + i.value, 0))}
                            </span>
                          )}
                        </button>

                        {soiExpanded && (
                          <div className="mt-3 space-y-3">
                            {/* Summary bar */}
                            <div className="grid grid-cols-4 gap-2">
                              <div className="bg-muted/30 rounded-lg p-2.5 text-center">
                                <div className="text-[10px] text-muted-foreground uppercase">Cost</div>
                                <div className="text-sm font-semibold">{formatCurrency(investments.reduce((s, i) => s + i.cost, 0))}</div>
                              </div>
                              <div className="bg-muted/30 rounded-lg p-2.5 text-center">
                                <div className="text-[10px] text-muted-foreground uppercase">Value</div>
                                <div className="text-sm font-semibold">{formatCurrency(investments.reduce((s, i) => s + i.value, 0))}</div>
                              </div>
                              <div className="bg-muted/30 rounded-lg p-2.5 text-center">
                                <div className="text-[10px] text-muted-foreground uppercase">Gain/Loss</div>
                                <div className={`text-sm font-semibold ${investments.reduce((s, i) => s + i.gainLoss, 0) >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                                  {formatCurrency(Math.abs(investments.reduce((s, i) => s + i.gainLoss, 0)))}
                                </div>
                              </div>
                              <div className="bg-muted/30 rounded-lg p-2.5 text-center">
                                <div className="text-[10px] text-muted-foreground uppercase">Multiple</div>
                                <div className="text-sm font-semibold">
                                  {(() => { const tc = investments.reduce((s, i) => s + i.cost, 0); return tc > 0 ? `${(investments.reduce((s, i) => s + i.value, 0) / tc).toFixed(2)}x` : '\u2014' })()}
                                </div>
                              </div>
                            </div>

                            {/* Table */}
                            <div className="overflow-x-auto rounded-lg border border-border">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="bg-muted/30 border-b border-border">
                                    <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Asset</th>
                                    <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Date</th>
                                    <th className="text-right px-3 py-2 font-semibold text-muted-foreground">Shares</th>
                                    <th className="text-right px-3 py-2 font-semibold text-muted-foreground">Cost</th>
                                    <th className="text-right px-3 py-2 font-semibold text-muted-foreground">Value</th>
                                    <th className="text-right px-3 py-2 font-semibold text-muted-foreground">Gain/Loss</th>
                                    <th className="text-right px-3 py-2 font-semibold text-muted-foreground">Cost/Sh</th>
                                    <th className="text-right px-3 py-2 font-semibold text-muted-foreground">FMV/Sh</th>
                                    <th className="text-right px-3 py-2 font-semibold text-muted-foreground">% Cap</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {investments.map((inv, i) => (
                                    <tr key={i} className="border-b border-border/50 hover:bg-muted/10">
                                      <td className="px-3 py-2 font-medium text-foreground">{inv.asset}</td>
                                      <td className="px-3 py-2 text-muted-foreground">{inv.investmentDate}</td>
                                      <td className="px-3 py-2 text-right">{inv.shares ? inv.shares.toLocaleString() : '\u2014'}</td>
                                      <td className="px-3 py-2 text-right">{formatCurrency(inv.cost)}</td>
                                      <td className="px-3 py-2 text-right">{formatCurrency(inv.value)}</td>
                                      <td className={`px-3 py-2 text-right ${inv.gainLoss >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                                        {formatCurrency(inv.gainLoss)}
                                      </td>
                                      <td className="px-3 py-2 text-right text-muted-foreground">{inv.costPerShare !== null ? `$${inv.costPerShare.toFixed(4)}` : '\u2014'}</td>
                                      <td className="px-3 py-2 text-right text-muted-foreground">{inv.fmvPerShare !== null ? `$${inv.fmvPerShare.toFixed(4)}` : '\u2014'}</td>
                                      <td className="px-3 py-2 text-right text-muted-foreground">{inv.percentOfPartnersCapital !== null ? `${inv.percentOfPartnersCapital.toFixed(2)}%` : '\u2014'}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Flags */}
                    {(selected.redFlags.length > 0 || selected.goodNews.length > 0) && (
                      <div className="grid grid-cols-2 gap-3">
                        {selected.goodNews.length > 0 && (
                          <div className="bg-emerald-500/5 border border-emerald-500/10 rounded-lg p-3">
                            <div className="text-[10px] text-emerald-500 font-semibold uppercase mb-2">Good News</div>
                            {selected.goodNews.map((g, i) => (
                              <p key={i} className="text-xs text-foreground/80 leading-relaxed">+ {g}</p>
                            ))}
                          </div>
                        )}
                        {selected.redFlags.length > 0 && (
                          <div className="bg-red-500/5 border border-red-500/10 rounded-lg p-3">
                            <div className="text-[10px] text-red-500 font-semibold uppercase mb-2">Red Flags</div>
                            {selected.redFlags.map((r, i) => (
                              <p key={i} className="text-xs text-foreground/80 leading-relaxed">{"\u26a0"} {r}</p>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Communications Timeline */}
                    {detail && detail.notes.length > 0 && (
                      <div>
                        <div className="flex items-center justify-between mb-3">
                          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Communications</h3>
                          <span className="text-[10px] text-muted-foreground">{detail.touchpoints30d} in last 30d</span>
                        </div>
                        <div className="space-y-1.5">
                          {detail.notes.map((note) => {
                            const source = detectSource(note.body)
                            return (
                              <div key={note.id}
                                className="flex items-center gap-2 p-2.5 rounded-lg hover:bg-muted/30 cursor-pointer transition-colors group"
                                onClick={() => setSelectedNote({ body: note.body, date: note.date, source, companyName: selected.name })}
                              >
                                {source === "email" && <Mail className="w-3.5 h-3.5 text-blue-400 shrink-0" />}
                                {source === "whatsapp" && <MessageCircle className="w-3.5 h-3.5 text-green-400 shrink-0" />}
                                {source === "granola" && <Mic className="w-3.5 h-3.5 text-violet-400 shrink-0" />}
                                {source === "update" && <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />}
                                <span className="text-[10px] text-muted-foreground shrink-0 w-20">{note.date}</span>
                                <span className="text-xs text-foreground/70 truncate flex-1">
                                  {note.body.split("\n").find(l => /^Summary:/i.test(l))?.replace(/^Summary:\s*/i, "") || note.body.slice(0, 100)}
                                </span>
                                <ChevronRight className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {detail && detail.notes.length === 0 && (
                      <div className="text-center py-8 text-sm text-muted-foreground">
                        No communications logged yet. Use the + button to add context.
                      </div>
                    )}
                  </>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Communication Modal */}
      {selectedNote && (
        <CommunicationModal
          isOpen={!!selectedNote}
          onClose={() => setSelectedNote(null)}
          note={selectedNote}
        />
      )}
    </div>
  )
}
