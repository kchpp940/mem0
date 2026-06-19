export type Category = "personal" | "work" | "health" | "finance" | "travel" | "education" | "preferences" | "relationships"
export type Client = "chrome" | "chatgpt" | "cursor" | "windsurf" | "terminal" | "api"
export type FeedbackStatusType = "unreviewed" | "confirmed" | "incorrect" | "outdated" | "needs_review"

export interface Memory {
  id: string
  memory: string
  metadata: any
  client: Client
  categories: Category[]
  created_at: number
  app_name: string
  state: "active" | "paused" | "archived" | "deleted"
  feedback_status?: FeedbackStatusType
}