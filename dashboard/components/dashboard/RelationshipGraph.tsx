"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Users, Search, ArrowRight, X, Link2, Mail, Calendar, Linkedin, Globe } from "lucide-react"
import { useRelationships, useIntroPath, useRelationshipStats, type RelConnection } from "@/lib/hooks/useDashboardData"
import { cn } from "@/lib/utils"

const relTypeConfig: Record<string, { label: string; icon: typeof Mail; color: string }> = {
  email_thread: { label: "Email", icon: Mail, color: "text-blue-400" },
  meeting: { label: "Meeting", icon: Calendar, color: "text-green-400" },
  linkedin_connection: { label: "LinkedIn", icon: Linkedin, color: "text-sky-400" },
  recommendation: { label: "Rec", icon: Link2, color: "text-purple-400" },
  co_founder: { label: "Co-founder", icon: Users, color: "text-amber-400" },
  advisor: { label: "Advisor", icon: Globe, color: "text-emerald-400" },
}

function ConnectionRow({ conn }: { conn: RelConnection }) {
  const config = relTypeConfig[conn.rel_type] || { label: conn.rel_type, icon: Link2, color: "text-zinc-400" }
  const Icon = config.icon

  return (
    <div className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-white/5 transition-colors">
      <Icon className={cn("h-4 w-4 shrink-0", config.color)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-zinc-200 truncate">
            {conn.person.name}
          </span>
          {conn.strength > 1 && (
            <span className="text-[10px] font-mono text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded">
              {conn.strength}x
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-xs text-zinc-500">
          {conn.person.company && <span>{conn.person.company}</span>}
          {conn.person.company && conn.context && <span>·</span>}
          {conn.context && <span className="truncate">{conn.context}</span>}
        </div>
      </div>
      <span className={cn("text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded border", config.color, "bg-white/5 border-white/10")}>
        {config.label}
      </span>
    </div>
  )
}

export function RelationshipGraph() {
  const [searchQuery, setSearchQuery] = useState("")
  const [activePerson, setActivePerson] = useState<string | null>(null)
  const [introFrom, setIntroFrom] = useState("")
  const [introTo, setIntroTo] = useState("")
  const [showIntroPath, setShowIntroPath] = useState(false)

  const { data: statsData } = useRelationshipStats()
  const { data: connectionsData, isLoading: loadingConnections } = useRelationships(activePerson)
  const { data: pathData, isLoading: loadingPath } = useIntroPath(
    showIntroPath ? introFrom : null,
    showIntroPath ? introTo : null
  )

  const handleSearch = () => {
    if (searchQuery.trim()) {
      setActivePerson(searchQuery.trim())
      setShowIntroPath(false)
    }
  }

  const handleIntroSearch = () => {
    if (introFrom.trim() && introTo.trim()) {
      setShowIntroPath(true)
      setActivePerson(null)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-white/10 bg-zinc-900/50 backdrop-blur"
    >
      <div className="flex items-center justify-between p-4 border-b border-white/5">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-violet-400" />
          <h3 className="text-sm font-medium text-zinc-200">Relationship Graph</h3>
          {statsData && (
            <span className="text-[10px] text-zinc-500 font-mono">
              {statsData.people} people · {statsData.relationships} connections
            </span>
          )}
        </div>
      </div>

      <div className="p-4 space-y-3">
        {/* Connection search */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="Search by email or name..."
              className="w-full pl-8 pr-3 py-2 text-sm bg-zinc-800/50 border border-white/10 rounded-lg text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-500/50"
            />
          </div>
          <button
            onClick={handleSearch}
            className="px-3 py-2 text-xs font-medium bg-violet-500/20 text-violet-300 border border-violet-500/30 rounded-lg hover:bg-violet-500/30 transition-colors"
          >
            Search
          </button>
        </div>

        {/* Intro path search */}
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={introFrom}
            onChange={(e) => setIntroFrom(e.target.value)}
            placeholder="From (email/name)"
            className="flex-1 px-3 py-1.5 text-xs bg-zinc-800/50 border border-white/10 rounded-lg text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-500/50"
          />
          <ArrowRight className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
          <input
            type="text"
            value={introTo}
            onChange={(e) => setIntroTo(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleIntroSearch()}
            placeholder="To (email/name)"
            className="flex-1 px-3 py-1.5 text-xs bg-zinc-800/50 border border-white/10 rounded-lg text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-500/50"
          />
          <button
            onClick={handleIntroSearch}
            className="px-2.5 py-1.5 text-[10px] font-medium bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded-lg hover:bg-emerald-500/30 transition-colors whitespace-nowrap"
          >
            Intro Path
          </button>
        </div>

        {/* Results */}
        <AnimatePresence mode="wait">
          {/* Connections list */}
          {activePerson && (
            <motion.div
              key="connections"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-zinc-500">
                  Connections for <span className="text-zinc-300">{activePerson}</span>
                </span>
                <button onClick={() => setActivePerson(null)} className="text-zinc-500 hover:text-zinc-300">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              {loadingConnections ? (
                <div className="text-xs text-zinc-500 py-4 text-center">Loading...</div>
              ) : !connectionsData?.connections?.length ? (
                <div className="text-xs text-zinc-500 py-4 text-center">No connections found</div>
              ) : (
                <div className="space-y-0.5 max-h-64 overflow-y-auto">
                  {connectionsData.connections.map((conn, i) => (
                    <ConnectionRow key={i} conn={conn} />
                  ))}
                </div>
              )}
            </motion.div>
          )}

          {/* Intro path */}
          {showIntroPath && (
            <motion.div
              key="intro-path"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-zinc-500">
                  Path: <span className="text-zinc-300">{introFrom}</span>
                  <ArrowRight className="inline h-3 w-3 mx-1" />
                  <span className="text-zinc-300">{introTo}</span>
                </span>
                <button onClick={() => setShowIntroPath(false)} className="text-zinc-500 hover:text-zinc-300">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              {loadingPath ? (
                <div className="text-xs text-zinc-500 py-4 text-center">Searching...</div>
              ) : !pathData?.path?.length ? (
                <div className="text-xs text-zinc-500 py-4 text-center">No connection path found</div>
              ) : (
                <div className="flex items-center gap-1 flex-wrap py-2">
                  {pathData.path.map((step, i) => (
                    <div key={i} className="flex items-center gap-1">
                      {i > 0 && (
                        <span className="text-[10px] text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded">
                          {step.via_rel_type}
                        </span>
                      )}
                      {i > 0 && <ArrowRight className="h-3 w-3 text-zinc-600" />}
                      <span className={cn(
                        "text-sm px-2 py-1 rounded-lg border",
                        i === 0 ? "bg-violet-500/10 border-violet-500/20 text-violet-300" :
                        i === pathData.path.length - 1 ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" :
                        "bg-zinc-800 border-white/10 text-zinc-300"
                      )}>
                        {step.person.name}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Stats summary when idle */}
        {!activePerson && !showIntroPath && statsData && statsData.relationships > 0 && (
          <div className="flex gap-3 pt-2">
            {Object.entries(statsData.by_type).slice(0, 4).map(([type, count]) => {
              const config = relTypeConfig[type] || { label: type, icon: Link2, color: "text-zinc-400" }
              return (
                <div key={type} className="flex items-center gap-1.5 text-xs text-zinc-500">
                  <span className={config.color}>{count}</span>
                  <span>{config.label}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </motion.div>
  )
}
