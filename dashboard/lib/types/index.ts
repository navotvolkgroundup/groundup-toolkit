export type ServiceStatus = "active" | "inactive" | "degraded"

export type ServiceCategory =
  | "Deal Sourcing"
  | "Portfolio Monitoring"
  | "Scheduling"
  | "Content & Comms"
  | "Internal Ops"

export interface Service {
  id: string
  name: string
  description: string
  category: ServiceCategory
  icon: string
  status: ServiceStatus
  lastRun: string
  canToggle: boolean
  enabledForUser?: boolean
  helpText: string
  trigger: string
  commands?: string[]
}

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: Date
  serviceContext?: string
}

export interface TeamMember {
  id: string
  name: string
  avatar?: string
}

export interface ActivityEntry {
  id: string
  serviceName: string
  action: string
  triggeredBy: string
  timestamp: string
}

export type NotificationLevel = "info" | "warning" | "error" | "success"

export interface Notification {
  id: string
  serviceName: string
  serviceIcon: string
  message: string
  level: NotificationLevel
  timestamp: string
  read: boolean
}
