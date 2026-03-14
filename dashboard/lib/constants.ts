/**
 * Centralized HubSpot constants — owner IDs, pipeline stages, and closed stages.
 * Single source of truth used by all dashboard API routes.
 */

// HubSpot owner ID → display name
export const OWNER_NAMES: Record<string, string> = {
  "76836577": "Navot",
  "7042119": "Jordan",
  "80040886": "Cory",
  "78681903": "David",
  "80351816": "Allie",
  "80033101": "Shira",
}

// Pipeline stages in display order
export const PIPELINE_STAGES = [
  { id: "qualifiedtobuy", label: "Sourcing", order: 0 },
  { id: "appointmentscheduled", label: "Screening", order: 1 },
  { id: "presentationscheduled", label: "First Meeting", order: 2 },
  { id: "decisionmakerboughtin", label: "IC Review", order: 3 },
  { id: "contractsent", label: "Due Diligence", order: 4 },
  { id: "closedwon", label: "Term Sheet Offered", order: 5 },
  { id: "1112320899", label: "Term Sheet Signed", order: 6 },
  { id: "1112320900", label: "Investment Closed", order: 7 },
  { id: "1008223160", label: "Portfolio Monitoring", order: 8 },
  { id: "1138024523", label: "Keep on Radar", order: 9 },
  { id: "closedlost", label: "Passed", order: 10 },
] as const

// Stage ID → label lookup
export const STAGE_LABELS: Record<string, string> = Object.fromEntries(
  PIPELINE_STAGES.map((s) => [s.id, s.label])
)

// Stages considered "closed" (no longer active in pipeline)
export const CLOSED_STAGES = new Set([
  "closedwon",
  "closedlost",
  "1112320899",
  "1112320900",
  "1008223160",
])
